from typing import List


def create_wav_buffer(audio_buffer: bytes, sample_rate: int, channels: int) -> bytes:
    """Create proper WAV file buffer with headers for PCM data"""
    length = len(audio_buffer)

    # WAV file header
    riff = b'RIFF'
    file_size = (36 + length).to_bytes(4, 'little')
    wave = b'WAVE'
    fmt = b'fmt '
    subchunk1_size = (16).to_bytes(4, 'little')
    audio_format = (1).to_bytes(2, 'little')  # PCM
    num_channels = channels.to_bytes(2, 'little')
    sample_rate_bytes = sample_rate.to_bytes(4, 'little')
    byte_rate = (sample_rate * channels * 2).to_bytes(4, 'little')
    block_align = (channels * 2).to_bytes(2, 'little')
    bits_per_sample = (16).to_bytes(2, 'little')
    data = b'data'
    subchunk2_size = length.to_bytes(4, 'little')

    # Combine all parts
    wav_buffer = (riff + file_size + wave + fmt + subchunk1_size + audio_format +
                  num_channels + sample_rate_bytes + byte_rate + block_align +
                  bits_per_sample + data + subchunk2_size + audio_buffer)

    return wav_buffer
