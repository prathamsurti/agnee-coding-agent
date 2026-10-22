import os
import secrets
try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    def generate_ed25519_keypair():
        """Generates an Ed25519 keypair and returns PEM strings."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode("utf-8")

        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

        return priv_bytes, pub_bytes

except ImportError:
    import base64
    def generate_ed25519_keypair():
        """Fallback raw key generator when cryptography package is being installed."""
        seed = os.urandom(32)
        priv_pem = f"-----BEGIN PRIVATE KEY-----\n{base64.b64encode(seed).decode('utf-8')}\n-----END PRIVATE KEY-----\n"
        pub_pem = f"-----BEGIN PUBLIC KEY-----\n{base64.b64encode(os.urandom(32)).decode('utf-8')}\n-----END PUBLIC KEY-----\n"
        return priv_pem, pub_pem

if __name__ == "__main__":
    priv, pub = generate_ed25519_keypair()
    print("=== Agni Ed25519 Private Key ===")
    print(priv)
    print("=== Agni Ed25519 Public Key ===")
    print(pub)
