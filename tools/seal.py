"""Lock / unlock Reel's private settings (your Supabase project URL + key) with a passphrase.

    python tools/seal.py lock secrets/seed.json secrets/seed.json.enc     # encrypt (asks for a passphrase)
    python tools/seal.py open secrets/seed.json.enc seed.json             # decrypt (asks for it again)

Encryption: scrypt (N=2^15, r=8, p=1) derives a key from the passphrase; Fernet (AES-128-CBC + HMAC-SHA256)
encrypts and authenticates the file. Set REEL_PASSPHRASE to skip the prompt.
"""
import os, sys, json, base64, hashlib, getpass
from cryptography.fernet import Fernet, InvalidToken


def derive(passphrase, salt):
    raw = hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return base64.urlsafe_b64encode(raw)


def lock(src, dst, passphrase):
    salt = os.urandom(16)
    token = Fernet(derive(passphrase, salt)).encrypt(open(src, 'rb').read())
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump({'format': 'reel-seal-1', 'kdf': 'scrypt', 'n': 2 ** 15, 'r': 8, 'p': 1,
                   'salt': base64.b64encode(salt).decode(), 'data': token.decode()}, f, indent=1)


def unlock(src, passphrase):
    box = json.load(open(src, encoding='utf-8'))
    return Fernet(derive(passphrase, base64.b64decode(box['salt']))).decrypt(box['data'].encode())


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('lock', 'open'):
        print(__doc__)
        return 1
    mode, src, dst = sys.argv[1:]
    env = os.environ.get('REEL_PASSPHRASE')
    if mode == 'lock':
        pw = env or getpass.getpass('New passphrase: ')
        if not env and pw != getpass.getpass('Again: '):
            print('Passphrases did not match.')
            return 1
        lock(src, dst, pw)
        print(f'Locked -> {dst}')
        return 0
    for attempt in range(1 if env else 3):
        pw = env or getpass.getpass('Reel passphrase (Enter to skip cloud sync): ')
        if not pw:
            print('Skipped - you can paste your Supabase details later in Reel > Library settings.')
            return 2
        try:
            data = unlock(src, pw)
        except InvalidToken:
            print('Wrong passphrase.')
            continue
        with open(dst, 'wb') as f:
            f.write(data)
        print('Unlocked your cloud settings.')
        return 0
    return 3


if __name__ == '__main__':
    sys.exit(main())
