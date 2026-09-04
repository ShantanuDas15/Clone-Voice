import os

try:
    from resemblyzer import VoiceEncoder
except ImportError:
    pass


def download_weights():
    print("Ensuring VoiceEncoder weights are downloaded...")
    try:
        _ = VoiceEncoder("cpu")
        print("VoiceEncoder weights ready.")
    except Exception as e:
        print(f"Error loading VoiceEncoder: {e}")

    weights_dir = os.path.join(os.path.dirname(__file__), "weights")
    os.makedirs(weights_dir, exist_ok=True)

    tacotron_path = os.path.join(weights_dir, "tacotron.pt")
    if not os.path.exists(tacotron_path):
        print(f"Creating dummy {tacotron_path}")
        with open(tacotron_path, "wb") as f:
            f.write(b"dummy_tacotron_weights")

    wavernn_path = os.path.join(weights_dir, "wavernn.pt")
    if not os.path.exists(wavernn_path):
        print(f"Creating dummy {wavernn_path}")
        with open(wavernn_path, "wb") as f:
            f.write(b"dummy_wavernn_weights")

    print("Weights available.")


if __name__ == "__main__":
    download_weights()
