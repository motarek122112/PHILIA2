// Observe a provider-supplied Retry-After; do not guess a quota or retry an action.
export class ProviderCooldown {
  constructor(now = Date.now) { this.now = now; this.until = 0; this.diagnostic = null; }
  remember(diagnostic) {
    const seconds = diagnostic.rate_limit?.retry_after_seconds;
    if (diagnostic.provider_status !== 429 || !Number.isFinite(seconds) || seconds <= 0 || seconds > 604800) return;
    const until = this.now() + seconds * 1000;
    if (until >= this.until) { this.until = until; this.diagnostic = diagnostic; }
  }
  remaining() {
    if (!this.diagnostic || this.now() >= this.until) return null;
    return { ...this.diagnostic, rate_limit: { ...this.diagnostic.rate_limit,
      retry_after_seconds: Math.ceil((this.until - this.now()) / 1000) } };
  }
}
