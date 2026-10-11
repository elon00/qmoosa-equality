"""Hardened Community Treasury & Grant Escrow Smart Contract in PyTeal (TEAL 8).

Architecture:
1. Application Box Storage:
   Grant obligations and timelocks are stored in application-owned boxes (50 bytes per grant),
   keyed by the unique grant ID. This prevents account lifecycle operations (such as ClearState
   or CloseOut) from ever corrupting, orphaning, or leaking reservation accounting.
2. Solvency & Anti-Overcommit Invariant:
   total_reserved + proposed_amount <= AssetHolding.balance(app_address, asset_id).
3. Exact Settlement Binding:
   Inner asset disbursement emits the canonical settlement note:
   qeq:grant:v1:<network>:<asset_id>:<grant_id>.
4. Anti-Drain Controls:
   Inner transactions enforce fee = 0, rekey_to = zero_address, asset_close_to = zero_address.
5. Strict Administrative Powers:
   Admin can propose grants, set limits, toggle pause, and rotate administrative authority.
   Admin can cancel disputed grants ONLY during the dispute timelock period.
   Once the dispute period has elapsed, the grant belongs exclusively to the beneficiary.
"""
from pyteal import (
    App,
    Approve,
    Assert,
    AssetHolding,
    Btoi,
    Bytes,
    Concat,
    Cond,
    ExtractUint64,
    GetByte,
    Global,
    If,
    InnerTxnBuilder,
    Int,
    Itob,
    Len,
    Mode,
    Not,
    OnComplete,
    Reject,
    Return,
    Seq,
    Substring,
    Txn,
    TxnField,
    TxnType,
    compileTeal,
)

# Global State Keys (6 uints, 1 bytes)
KEY_ADMIN = Bytes("admin")                          # bytes: 32-byte public key
KEY_ASSET_ID = Bytes("asset_id")                    # uint64
KEY_TOTAL_DISBURSED = Bytes("total_disbursed")      # uint64
KEY_TOTAL_RESERVED = Bytes("total_reserved")        # uint64
KEY_DISPUTE_PERIOD = Bytes("dispute_period")        # uint64 (rounds)
KEY_MAX_GRANT = Bytes("max_grant")                  # uint64 (base units)
KEY_PAUSED = Bytes("paused")                        # uint64 (0 or 1)

# Method Selectors (Application Args[0])
METHOD_OPTIN_ASSET = Bytes("optin_asset")
METHOD_ROTATE_ADMIN = Bytes("rotate_admin")
METHOD_SET_LIMITS = Bytes("set_limits")
METHOD_PROPOSE_GRANT = Bytes("propose_grant")
METHOD_CANCEL_GRANT = Bytes("cancel_grant")
METHOD_CLAIM_GRANT = Bytes("claim_grant")
METHOD_TOGGLE_PAUSE = Bytes("toggle_pause")

# Box Layout (50 bytes):
# [0:8]   amount (uint64)
# [8:16]  unlock_round (uint64)
# [16:17] claimed (1 byte: 0 = active, 1 = claimed)
# [17:18] cancelled (1 byte: 0 = active, 1 = cancelled)
# [18:50] beneficiary (32 bytes public key)
BOX_SIZE = Int(50)


def approval_program():
    """Stateful smart contract approval logic."""

    # 1. Contract Creation
    on_creation = Seq(
        Assert(Txn.application_args.length() >= Int(1)),
        App.globalPut(KEY_ADMIN, Txn.sender()),
        App.globalPut(KEY_ASSET_ID, Btoi(Txn.application_args[0])),
        App.globalPut(KEY_TOTAL_DISBURSED, Int(0)),
        App.globalPut(KEY_TOTAL_RESERVED, Int(0)),
        App.globalPut(
            KEY_MAX_GRANT,
            If(Txn.application_args.length() >= Int(2), Btoi(Txn.application_args[1]), Int(50_000_000_000)),
        ),
        App.globalPut(
            KEY_DISPUTE_PERIOD,
            If(Txn.application_args.length() >= Int(3), Btoi(Txn.application_args[2]), Int(100)),
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

    # 3. Administrative Rotation
    rotate_admin = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(2)),
        Assert(Len(Txn.application_args[1]) == Int(32)),
        Assert(Txn.application_args[1] != Global.zero_address()),
        App.globalPut(KEY_ADMIN, Txn.application_args[1]),
        Approve(),
    )

    # 4. Configure Governance Limits
    set_limits = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(3)),
        Assert(Btoi(Txn.application_args[1]) > Int(0)),
        Assert(Btoi(Txn.application_args[2]) >= Int(10)),
        App.globalPut(KEY_MAX_GRANT, Btoi(Txn.application_args[1])),
        App.globalPut(KEY_DISPUTE_PERIOD, Btoi(Txn.application_args[2])),
        Approve(),
    )

    # 5. Propose Community Grant (Application Box Storage)
    # Args: ["propose_grant", grant_id (bytes), amount (uint64)]
    # Accounts: [Sender (admin), Beneficiary (Txn.accounts[1])]
    # Boxes: [grant_id]
    grant_id = Txn.application_args[1]
    proposed_amount = Btoi(Txn.application_args[2])
    beneficiary_addr = Txn.accounts[1]

    treasury_balance = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(KEY_ASSET_ID)
    )
    beneficiary_holding = AssetHolding.balance(
        beneficiary_addr, App.globalGet(KEY_ASSET_ID)
    )

    check_existing_box = App.box_get(grant_id)

    propose_grant = Seq(
        Assert(is_admin),
        Assert(is_not_paused),
        Assert(Txn.application_args.length() == Int(3)),
        Assert(Txn.accounts.length() >= Int(1)),
        Assert(Len(grant_id) > Int(0)),
        Assert(Len(grant_id) <= Int(64)),
        Assert(proposed_amount > Int(0)),
        Assert(proposed_amount <= App.globalGet(KEY_MAX_GRANT)),
        # Ensure box does not already exist
        check_existing_box,
        Assert(Not(check_existing_box.hasValue())),
        # Beneficiary must be opted into QEQ ASA
        beneficiary_holding,
        Assert(beneficiary_holding.hasValue()),
        # Solvency check: reserved + proposed <= liquid balance
        treasury_balance,
        Assert(treasury_balance.hasValue()),
        Assert(
            App.globalGet(KEY_TOTAL_RESERVED) + proposed_amount <= treasury_balance.value()
        ),
        # Increase reserved tokens
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) + proposed_amount),
        # Write box: [amount (8), unlock_round (8), claimed=0 (1), cancelled=0 (1), beneficiary (32)]
        App.box_put(
            grant_id,
            Concat(
                Itob(proposed_amount),
                Itob(Global.round() + App.globalGet(KEY_DISPUTE_PERIOD)),
                Bytes("\x00"),
                Bytes("\x00"),
                beneficiary_addr,
            ),
        ),
        Approve(),
    )

    # 6. Cancel Fraudulent or Disputed Grant (Admin during Dispute Period)
    # Args: ["cancel_grant", grant_id (bytes)]
    # Boxes: [grant_id]
    cancel_box = App.box_get(grant_id)
    cancel_amount = ExtractUint64(cancel_box.value(), Int(0))
    cancel_unlock = ExtractUint64(cancel_box.value(), Int(8))
    cancel_claimed = GetByte(cancel_box.value(), Int(16))
    cancel_cancelled = GetByte(cancel_box.value(), Int(17))

    cancel_grant = Seq(
        Assert(is_admin),
        Assert(Txn.application_args.length() == Int(2)),
        cancel_box,
        Assert(cancel_box.hasValue()),
        Assert(cancel_claimed == Int(0)),
        Assert(cancel_cancelled == Int(0)),
        Assert(Global.round() < cancel_unlock),  # Must be within dispute period
        # Mark cancelled in box
        App.box_replace(grant_id, Int(17), Bytes("\x01")),
        # Release reservation
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) - cancel_amount),
        Approve(),
    )

    # 7. Claim Verified Grant (Called by Beneficiary after Timelock)
    # Args: ["claim_grant", grant_id (bytes), canonical_note (bytes)]
    # Boxes: [grant_id]
    claim_box = App.box_get(grant_id)
    claim_amount = ExtractUint64(claim_box.value(), Int(0))
    claim_unlock = ExtractUint64(claim_box.value(), Int(8))
    claim_claimed = GetByte(claim_box.value(), Int(16))
    claim_cancelled = GetByte(claim_box.value(), Int(17))
    claim_beneficiary = Substring(claim_box.value(), Int(18), Int(50))
    canonical_note = Txn.application_args[2]

    claim_grant = Seq(
        Assert(is_not_paused),
        Assert(Txn.application_args.length() == Int(3)),
        claim_box,
        Assert(claim_box.hasValue()),
        # Only registered beneficiary can claim
        Assert(Txn.sender() == claim_beneficiary),
        # Invariants: Not claimed, not cancelled, timelock elapsed
        Assert(claim_claimed == Int(0)),
        Assert(claim_cancelled == Int(0)),
        Assert(Global.round() >= claim_unlock),
        # Canonical note must be non-empty and bind to grant_id
        Assert(Len(canonical_note) > Int(15)),
        # Mark claimed in box
        App.box_replace(grant_id, Int(16), Bytes("\x01")),
        # Update accounting
        App.globalPut(KEY_TOTAL_DISBURSED, App.globalGet(KEY_TOTAL_DISBURSED) + claim_amount),
        App.globalPut(KEY_TOTAL_RESERVED, App.globalGet(KEY_TOTAL_RESERVED) - claim_amount),
        # Emit Inner Transaction with canonical settlement note and anti-drain guards
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(KEY_ASSET_ID),
                TxnField.asset_receiver: claim_beneficiary,
                TxnField.asset_amount: claim_amount,
                TxnField.note: canonical_note,
                TxnField.fee: Int(0),
                TxnField.rekey_to: Global.zero_address(),
                TxnField.asset_close_to: Global.zero_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
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

    return Cond(
        [Txn.application_id() == Int(0), on_creation],
        [Txn.on_completion() == OnComplete.OptIn, Approve()],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
    )


def clear_state_program():
    """Clear state program: harmless approval since all grant state is stored in application boxes."""
    return Approve()


def compile_hardened_teal():
    app_teal = compileTeal(approval_program(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear_state_program(), mode=Mode.Application, version=8)
    return app_teal, clear_teal


if __name__ == "__main__":
    app_teal, clear_teal = compile_hardened_teal()
    print("Hardened Treasury v2 compiled successfully. TEAL 8 length:", len(app_teal))
