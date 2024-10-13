from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


def generate_keys(print_keys: bool = False):
    """Generate RSA private and public keys."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # If true, print them in the .env format
    if print_keys:
        private_key_str = (
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            .decode()
            .replace("\n", "\\n")
        )

        public_key_str = (
            public_key.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.PKCS1
            )
            .decode()
            .replace("\n", "\\n")
        )

        print(f"PRIVATE_KEY={private_key_str}")
        print(f"PUBLIC_KEY={public_key_str}")
    return private_key, public_key


def load_private_key(private_key):
    """Load a private key from a PEM string or return the key if it's already an object."""
    if isinstance(private_key, str):
        private_key = serialization.load_pem_private_key(
            private_key.encode(),
            password=None,
            backend=default_backend()
        )
    return private_key


def load_public_key(public_key):
    """Load a public key from a PEM string or return the key if it's already an object."""
    if isinstance(public_key, str):
        public_key = serialization.load_pem_public_key(
            public_key.encode(),
            backend=default_backend()
        )
    return public_key


def sign_packet(packet: bytes, private_key):
    """Sign a packet using the provided private key."""
    private_key = load_private_key(private_key)
    packet_hash = hashes.Hash(hashes.SHA256())
    packet_hash.update(packet)
    digest = packet_hash.finalize()

    signature = private_key.sign(
        digest,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256(),
    )
    return signature


def verify_packet(packet: bytes, signature: bytes, public_key):
    """Verify a packet using the provided public key."""
    public_key = load_public_key(public_key)
    packet_hash = hashes.Hash(hashes.SHA256())
    packet_hash.update(packet)
    digest = packet_hash.finalize()

    try:
        public_key.verify(
            signature,
            digest,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False


def encrypt_packet(packet: bytes, public_key):
    """Encrypt a packet using the recipient's public key."""
    public_key = load_public_key(public_key)
    encrypted_packet = public_key.encrypt(
        packet,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return encrypted_packet


def decrypt_packet(encrypted_packet: bytes, private_key):
    """Decrypt a packet using the recipient's private key."""
    private_key = load_private_key(private_key)
    decrypted_packet = private_key.decrypt(
        encrypted_packet,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return decrypted_packet


if __name__ == "__main__":
    # Example usage
    private_key, public_key = generate_keys(print_keys=True)
    packet = b"Important data from API"

    signature = sign_packet(packet, private_key)
    is_verified = verify_packet(packet, signature, public_key)
    print("Packet is verified as coming from the API:", is_verified)

    encrypted_packet = encrypt_packet(packet, public_key)
    decrypted_packet = decrypt_packet(encrypted_packet, private_key)
    print("Decrypted packet:", decrypted_packet)
