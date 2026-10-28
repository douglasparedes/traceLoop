// AudioWorklet processor: batches mono Float32 frames into ~100ms blocks
// before posting to the main thread (avoids ~375 tiny messages/sec), which
// converts them to paced 16-bit PCM for the Muse Voice realtime proxy.
class FieldGuardPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = [];
    this.target = Math.max(1024, Math.floor(sampleRate / 10));
  }
  process(inputs) {
    const input = inputs[0];
    if (input && input[0] && input[0].length) {
      for (let i = 0; i < input[0].length; i++) this.buffer.push(input[0][i]);
      while (this.buffer.length >= this.target) {
        const chunk = this.buffer.splice(0, this.target);
        this.port.postMessage(new Float32Array(chunk));
      }
    }
    return true;
  }
}
registerProcessor("fieldguard-pcm", FieldGuardPCM);
