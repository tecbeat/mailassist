# Key Rotation

Rotate the master encryption key without downtime.

## Procedure

1. Set the old key as fallback:

    ```bash
    # In .env
    APP_SECRET_KEY_OLD=your-current-key
    APP_SECRET_KEY=your-new-key-min-32-chars
    ```

2. Restart the application:

    ```bash
    docker compose up -d
    ```

3. mailassist automatically re-encrypts all DEKs with the new KEK on startup.

4. After confirming everything works, remove `APP_SECRET_KEY_OLD`:

    ```bash
    # In .env — remove the line:
    # APP_SECRET_KEY_OLD=...
    ```

## How It Works

- On startup, if `APP_SECRET_KEY_OLD` is set, the app tries the new key first, then falls back to the old key for decryption
- Successfully decrypted credentials are re-encrypted with the new key
- After all credentials are re-encrypted, the old key is no longer needed
