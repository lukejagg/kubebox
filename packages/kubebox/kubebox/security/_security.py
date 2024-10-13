from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes


def generate_keys():
    """Generate RSA private and public keys."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def sign_packet(packet: bytes, private_key):
    """Sign a packet using the provided private key."""
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
    except:
        return False


if __name__ == "__main__":
    # Example usage
    private_key, public_key = generate_keys()
    packet = b"Important data from API"
    signature = sign_packet(packet, private_key)

    is_verified = verify_packet(packet, signature, public_key)
    if is_verified:
        print("Packet is verified as coming from the API.")
    else:
        print("Packet verification failed.")
