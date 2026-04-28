# Encryption

mailassist uses envelope encryption to protect stored credentials (IMAP passwords, API keys, CardDAV credentials).

## How It Works

```
APP_SECRET_KEY (KEK)
       │
       ▼
   ┌───────┐
   │  DEK  │ ← unique per record, encrypted by KEK
   └───┬───┘
       │
       ▼
   Credential (encrypted by DEK)
```

- **KEK** (Key Encryption Key): Derived from `APP_SECRET_KEY`. Never stored in the database.
- **DEK** (Data Encryption Key): A random key generated per credential. The DEK is encrypted by the KEK and stored alongside the ciphertext.

This means:

- Each credential has its own encryption key
- Compromising the database alone does not expose credentials
- Key rotation only requires re-encrypting DEKs, not all data

## Key Rotation

See [Key Rotation](../operations/key-rotation.md) for the step-by-step procedure.

## API Behavior

The API never returns encrypted values. Credential fields are write-only — you can set them but never read them back.
