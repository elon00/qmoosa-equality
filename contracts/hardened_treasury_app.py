"""Hardened Community Treasury & Grant Escrow Smart Contract in PyTeal (TEAL 8).
Implements explicit administrative rotation, reservation accounting, per-grant caps,
dispute-period cancellation, emergency pause, and inner-transaction anti-drain protections.
"""
from pyteal import (
    App,
    Approve,
    Assert,
    AssetHolding,
    Btoi,
    Bytes,
    Cond,
    Global,
    If,
    InnerTxnBuilder,
    Int,
    Len,
    Mode,
    OnComplete,
    Reject,
    Return,
    Seq,
    Subroutine,
    TealType,
    Txn,
    TxnField,
    TxnType,
    compileTeal,
)

# Global State Keys
KEY_ADMIN = Bytes("admin")
KEY_ASSET_ID = Bytes("asset_id")
KEY_TOTAL_DISBURSED = Bytes("total_disbursed")
KEY_TOTAL_RESERVED = Bytes("total_reserved")
KEY_DISPUTE_PERIOD = Bytes("dispute_period")
KEY_MAX_GRANT = Bytes("max_grant")
KEY_PAUSED = Bytes("paused")

# Local State Keys (Beneficiary Account)
KEY_PENDING_GRANT = Bytes("pending_grant")
KEY_UNLOCK_ROUND = Bytes("unlock_round")

# Method Names (Application Args[0])
METHOD_OPTIN_ASSET = Bytes("optin_asset")
METHOD_ROTATE_ADMIN = Bytes("rotate_admin")
METHOD_SET_LIMITS = Bytes("set_limits")
METHOD_PROPOSE_GRANT = Bytes("propose_grant")
METHOD_CANCEL_GRANT = Bytes("cancel_grant")
METHOD_CLAIM_GRANT = Bytes("claim_grant")
METHOD_TOGGLE_PAUSE = Bytes("toggle_pause")


def approval_program():
    """Stateful smart contract approval logic."""

    # 1. Contract Creation
    # Args: [asset_id (uint64), max_grant_amount (uint64), dispute_period_rounds (uint64)]
    on_creation = Seq(
        Assert(Txn.application_args.length() >= Int(1)),
        App.globalPut(KEY_ADMIN, Txn.sender()),
        App.globalPut(KEY_ASSET_ID, Btoi(Txn.application_args[0])),
        App.globalPut(KEY_TOTAL_DISBURSED, Int(0)),
        App.globalPut(KEY_TOTAL_RESERVED, Int(0)),
        App.globalPut(
            KEY_MAX_GRANT,
            If(Txn.application_args.length() >= Int(2), Btoi(Txn.application_args[1]), Int(50_000_000_000)),  # 50,000 QEQ default cap
        ),
        App.globalPut(
            KEY_DISPUTE_PERIOD,
            If(Txn.application_args.length() >= Int(3), Btoi(Txn.application_args[2]), Int(100)),  # ~100 rounds dispute period (~5 min)
        ),
        App.globalPut(KEY_PAUSED, Int(0)),
        Approve(),
    )

    is_admin = Txn.sender() == App.globalGet(KEY_ADMIN)
    is_not_paused = App.globalGet(KEY_PAUSED) == Int(0)

    # 2. Opt-In Contract Account to QEQ Asset
    optin_asset = Seq(
        Assert(is_admin),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(KEY_ASSET_ID),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
                TxnField.fee: Int(0),
                TxnField.rekey_to: Global.zero_address(),
                TxnField.asset_close_to: Global.zero_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    # 3. Secure Administrative Rotation
    # Args: ["rotate_admin", new_admin_address (32 bytes)]
    rotate_admin = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(2)),
        Assert(Len(Txn.application_args[1]) == Int(32)),  # Valid 32-byte public key
        Assert(Txn.application_args[1] != Global.zero_address()),
        App.globalPut(KEY_ADMIN, Txn.application_args[1]),
        Approve(),
    )

    # 4. Configure Governance Limits
    # Args: ["set_limits", max_grant (uint64), dispute_period (uint64)]
    set_limits = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(3)),
        Assert(Btoi(Txn.application_args[1]) > Int(0)),
        Assert(Btoi(Txn.application_args[2]) >= Int(10)),  # Minimum 10 rounds dispute timelock
        App.globalPut(KEY_MAX_GRANT, Btoi(Txn.application_args[1])),
        App.globalPut(KEY_DISPUTE_PERIOD, Btoi(Txn.application_args[2])),
        Approve(),
    )

    # 5. Propose Community Grant
    # Accounts: [Sender (admin), Beneficiary]
    # Args: ["propose_grant", amount (uint64)]
    proposed_amount = Btoi(Txn.application_args[1])
    beneficiary_has_no_active_grant = App.localGet(Int(1), KEY_PENDING_GRANT) == Int(0)
    treasury_balance = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(KEY_ASSET_ID)
    )
    beneficiary_holding = AssetHolding.balance(
        Txn.accounts[1], App.globalGet(KEY_ASSET_ID)
    )

    propose_grant = Seq(
        Assert(is_admin),
        Assert(is_not_paused),
        Assert(Txn.application_args.length() == Int(2)),
        Assert(Txn.accounts.length() >= Int(1)),
        Assert(proposed_amount > Int(0)),
        Assert(proposed_amount <= App.globalGet(KEY_MAX_GRANT)),
        Assert(App.optedIn(Int(1), Global.current_application_id())),
        beneficiary_holding,
        Assert(beneficiary_holding.hasValue()),  # Beneficiary must be opted into QEQ ASA
        Assert(beneficiary_has_no_active_grant),  # Prevents overwriting pending grants
        treasury_balance,
        Assert(treasury_balance.hasValue()),
        Assert(
            App.globalGet(KEY_TOTAL_RESERVED) + proposed_amount <= treasury_balance.value()
        ),  # Overcommit protection: total reserved + proposed must not exceed liquid balance
        # Reservation Accounting
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) + proposed_amount),
        # Store in Beneficiary's local state
        App.localPut(Int(1), KEY_PENDING_GRANT, proposed_amount),
        App.localPut(Int(1), KEY_UNLOCK_ROUND, Global.round() + App.globalGet(KEY_DISPUTE_PERIOD)),
        Approve(),
    )

    # 6. Cancel Fraudulent or Disputed Grant (Admin during Dispute Period)
    # Accounts: [Sender (admin), Beneficiary]
    # Args: ["cancel_grant"]
    pending_to_cancel = App.localGet(Int(1), KEY_PENDING_GRANT)
    cancel_grant = Seq(
        Assert(is_admin),
        Assert(Txn.accounts.length() >= Int(1)),
        Assert(pending_to_cancel > Int(0)),
        Assert(Global.round() < App.localGet(Int(1), KEY_UNLOCK_ROUND)),  # Must be within dispute period
        # Release reservation
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) - pending_to_cancel),
        App.localPut(Int(1), KEY_PENDING_GRANT, Int(0)),
        App.localPut(Int(1), KEY_UNLOCK_ROUND, Int(0)),
        Approve(),
    )

    # 7. Claim Verified Grant (Called by Beneficiary after timelock)
    # Args: ["claim_grant"]
    grant_amount = App.localGet(Int(0), KEY_PENDING_GRANT)
    unlock_round = App.localGet(Int(0), KEY_UNLOCK_ROUND)

    claim_grant = Seq(
        Assert(is_not_paused),
        Assert(grant_amount > Int(0)),
        Assert(Global.round() >= unlock_round),  # Timelock has elapsed
        # Disburse funds via Inner Transaction with strict anti-drain safeguards
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(KEY_ASSET_ID),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: grant_amount,
                TxnField.fee: Int(0),
                TxnField.rekey_to: Global.zero_address(),
                TxnField.asset_close_to: Global.zero_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        # Update ledger accounting
        App.globalPut(KEY_TOTAL_DISBURSED, App.globalGet(KEY_TOTAL_DISBURSED) + grant_amount),
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) - grant_amount),
        # Clear local state to prevent replay / double claim
        App.localPut(Int(0), KEY_PENDING_GRANT, Int(0)),
        App.localPut(Int(0), KEY_UNLOCK_ROUND, Int(0)),
        Approve(),
    )

    # 8. Emergency Toggle Pause
    toggle_pause = Seq(
        Assert(is_admin),
        App.globalPut(KEY_PAUSED, If(App.globalGet(KEY_PAUSED) == Int(0), Int(1), Int(0))),
        Approve(),
    )

    handle_noop = Cond(
        [Txn.application_args[0] == METHOD_OPTIN_ASSET, optin_asset],
        [Txn.application_args[0] == METHOD_ROTATE_ADMIN, rotate_admin],
        [Txn.application_args[0] == METHOD_SET_LIMITS, set_limits],
        [Txn.application_args[0] == METHOD_PROPOSE_GRANT, propose_grant],
        [Txn.application_args[0] == METHOD_CANCEL_GRANT, cancel_grant],
        [Txn.application_args[0] == METHOD_CLAIM_GRANT, claim_grant],
        [Txn.application_args[0] == METHOD_TOGGLE_PAUSE, toggle_pause],
    )

    # Beneficiary opts into application local state
    handle_optin = Seq(
        App.localPut(Int(0), KEY_PENDING_GRANT, Int(0)),
        App.localPut(Int(0), KEY_UNLOCK_ROUND, Int(0)),
        Approve(),
    )

    # CloseOut is rejected if account has an active pending grant
    handle_closeout = Seq(
        Assert(App.localGet(Int(0), KEY_PENDING_GRANT) == Int(0)),
        Approve(),
    )

    return Cond(
        [Txn.application_id() == Int(0), on_creation],
        [Txn.on_completion() == OnComplete.OptIn, handle_optin],
        [Txn.on_completion() == OnComplete.CloseOut, handle_closeout],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
    )


def clear_state_program():
    """Clear state program: safely decrements global reserved tokens if sender had a pending grant."""
    pending = App.localGet(Int(0), KEY_PENDING_GRANT)
    return Seq(
        If(
            pending > Int(0),
            App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) - pending),
        ),
        Approve(),
    )


def compile_hardened_teal():
    app_teal = compileTeal(approval_program(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear_state_program(), mode=Mode.Application, version=8)
    return app_teal, clear_teal


if __name__ == "__main__":
    app_teal, clear_teal = compile_hardened_teal()
    print("Hardened Treasury compiled successfully. TEAL 8 length:", len(app_teal))
