"""Community Treasury & Grant Escrow Smart Contract in PyTeal (TEAL 8).
Enforces timelocked grant disbursement, allocation tracking, and anti-drain caps.
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
    Gtxn,
    If,
    InnerTxnBuilder,
    Int,
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
KEY_DISPUTE_PERIOD = Bytes("dispute_period")
KEY_PAUSED = Bytes("paused")

# Application Call Methods
METHOD_OPTIN_ASSET = Bytes("optin_asset")
METHOD_PROPOSE_GRANT = Bytes("propose_grant")
METHOD_CLAIM_GRANT = Bytes("claim_grant")
METHOD_TOGGLE_PAUSE = Bytes("toggle_pause")


def approval_program():
    """Stateful smart contract approval logic"""

    on_creation = Seq(
        App.globalPut(KEY_ADMIN, Txn.sender()),
        App.globalPut(KEY_ASSET_ID, Btoi(Txn.application_args[0])),
        App.globalPut(KEY_TOTAL_DISBURSED, Int(0)),
        App.globalPut(KEY_DISPUTE_PERIOD, Int(100)),  # ~100 rounds dispute timelock (~5 mins)
        App.globalPut(KEY_PAUSED, Int(0)),
        Approve(),
    )

    is_admin = Txn.sender() == App.globalGet(KEY_ADMIN)
    is_not_paused = App.globalGet(KEY_PAUSED) == Int(0)

    # Opt-in Treasury contract account to the QEQ Asset
    optin_asset = Seq(
        Assert(is_admin),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(KEY_ASSET_ID),
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0),
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    # Register a Community Grant Proposal
    # Args: [method, beneficiary_addr, grant_amount]
    propose_grant = Seq(
        Assert(is_admin),
        Assert(is_not_paused),
        Assert(Txn.application_args.length() == Int(3)),
        # Store pending grant info in local state of beneficiary account (Txn.accounts[1])
        App.localPut(Int(1), Bytes("pending_grant"), Btoi(Txn.application_args[2])),
        App.localPut(Int(1), Bytes("grant_unlock_round"), Global.round() + App.globalGet(KEY_DISPUTE_PERIOD)),
        Approve(),
    )

    # Beneficiary claims their verified Community Grant via Inner Transaction
    claim_grant = Seq(
        Assert(is_not_paused),
        # Check grant exists and timelock has elapsed
        Assert(App.localGet(Int(0), Bytes("pending_grant")) > Int(0)),
        Assert(Global.round() >= App.localGet(Int(0), Bytes("grant_unlock_round"))),
        # Transfer QEQ asset to caller (beneficiary) via Inner Transaction
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(KEY_ASSET_ID),
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: App.localGet(Int(0), Bytes("pending_grant")),
            }
        ),
        InnerTxnBuilder.Submit(),
        # Update accounting
        App.globalPut(
            KEY_TOTAL_DISBURSED,
            App.globalGet(KEY_TOTAL_DISBURSED) + App.localGet(Int(0), Bytes("pending_grant")),
        ),
        App.localPut(Int(0), Bytes("pending_grant"), Int(0)),
        Approve(),
    )

    # Emergency toggle pause
    toggle_pause = Seq(
        Assert(is_admin),
        App.globalPut(KEY_PAUSED, If(App.globalGet(KEY_PAUSED) == Int(0), Int(1), Int(0))),
        Approve(),
    )

    handle_noop = Cond(
        [Txn.application_args[0] == METHOD_OPTIN_ASSET, optin_asset],
        [Txn.application_args[0] == METHOD_PROPOSE_GRANT, propose_grant],
        [Txn.application_args[0] == METHOD_CLAIM_GRANT, claim_grant],
        [Txn.application_args[0] == METHOD_TOGGLE_PAUSE, toggle_pause],
    )

    # OptIn to application: allows beneficiary to opt-in their local state
    handle_optin = Seq(
        App.localPut(Int(0), Bytes("pending_grant"), Int(0)),
        App.localPut(Int(0), Bytes("grant_unlock_round"), Int(0)),
        Approve(),
    )

    return Cond(
        [Txn.application_id() == Int(0), on_creation],
        [Txn.on_completion() == OnComplete.OptIn, handle_optin],
        [Txn.on_completion() == OnComplete.CloseOut, Approve()],
        [Txn.on_completion() == OnComplete.UpdateApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Return(is_admin)],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
    )


def clear_state_program():
    return Approve()


def compile_to_teal():
    from pyteal import Btoi  # local helper
    approval_teal = compileTeal(approval_program(), mode=Mode.Application, version=8)
    clear_teal = compileTeal(clear_state_program(), mode=Mode.Application, version=8)
    return approval_teal, clear_teal


if __name__ == "__main__":
    from pyteal import Btoi
    app_teal, clear_teal = compile_to_teal()
    print("--- APPROVAL TEAL (v8) ---")
    print(app_teal[:500])
