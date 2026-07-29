# Credential migration required before merge

This branch removes a previously tracked `.env` and committed credential defaults. Removing them from the current tree does **not** remove them from Git history. Treat every credential that was committed as compromised.

## Before pulling or merging

1. Back up your current `.env` **outside this repository**.
2. Verify that the backup exists and is not inside a Git-controlled or shared folder.
3. Rotate the affected MySQL and mail credentials in their respective services.
4. Replace the values in your backed-up local file with the newly rotated credentials.

Do not paste credentials into a pull request, issue, commit, chat message, or review document.

## After updating the checkout

1. Restore the local file as `.env` at the repository root if Git removed it.
2. Rename the database variable from `DB_PASS` to `DB_PASSWORD` if necessary.
3. Compare the local file with `.env.example` and add any missing keys.
4. Confirm that `.env` remains ignored:

   ```text
   git check-ignore -v .env
   ```

5. Start the intended application mode and verify its database connection.

Desktop mode continues to use SQLite and does not require `DB_PASSWORD`.

## Git history

The old values remain recoverable from earlier commits even after rotation. After credentials are rotated and all collaborators coordinate a maintenance window, decide whether to rewrite repository history. A history rewrite requires force-pushing rewritten branches and having every clone re-cloned or carefully reset; it must not be performed casually.
