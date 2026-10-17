# Archived branch migrations

These files preserve the history of `main` and `ver2`. Do not run this directory
against the consolidated schema.

The supported sequence is `database/migrations/0001` through `0016`, in filename
order, each file in its own transaction. Director roles and role administration
are ported into `0014` and `0015`. The old vacation trigger would deduct days a
second time alongside the current reservation ledger and is intentionally not
installed. Request review and HR document fulfillment remain separate stages.

A database that actually ran the archived migrations needs a schema/data audit
before migration; this is not a downgrade script for that database.
