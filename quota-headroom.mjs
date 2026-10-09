// Advisory per-process rate headroom from the provider's REAL rate-limit headers.
// This protects a shared Groq organization from predictable excess requests.
// It does not create answers or route conversation: EVERY successful message
// still goes to the LLM. Other Render instances may have different snapshots.
export class ProviderTokenHeadroom {
  constructor(now = Date.now) {
    this.now = now;
    this.remaining = null;
    this.resetAt = 0;
    this.ratio = 0.27;
    this.samples = 0;
  }
  estimate(promptCharacters, reservedOutputTokens) {
    const characters = Math.max(0, Number(promptCharacters) || 0);
    const output = Math.max(0, Number(reservedOutputTokens) || 0);
    // The ratio is calibrated from successful provider usage, not hardcoded
    // as a fact about token counts in Arabic or mixed-script requests.
    return Math.ceil(characters * this.ratio + output + 90);
  }
  observe(rateLimit, promptCharacters = 0, usage = null) {
    const left = rateLimit?.tokens_remaining_minute;
    const reset = rateLimit?.tokens_reset_seconds;
    if (Number.isFinite(left) && left >= 0 && Number.isFinite(reset) && reset > 0 && reset <= 120) {
      this.remaining = left;
      this.resetAt = this.now() + reset * 1000;
    }
    const actual = usage?.prompt_tokens;
    if (Number.isFinite(actual) && actual > 0 && promptCharacters > 0) {
      const ratio = actual / promptCharacters;
      if (ratio >= 0.15 && ratio <= 0.8) {
        this.ratio = this.samples ? this.ratio * 0.65 + ratio * 0.35 : ratio;
        this.samples++;
      }
    }
  }
  reserve(estimateTokens) {
    if (this.remaining === null || this.now() >= this.resetAt) {
      this.remaining = null;
      return null;
    }
    // A small uncertainty allowance: only defer when headroom is known to be
    // too small, and do not turn estimated usage into a fake provider 429.
    if (this.remaining < estimateTokens) {
      return {
        code: 'AI_RATE_LIMIT', retryable: true, provider_status: null,
        provider_error_kind: 'provider_reported_token_headroom',
        rate_limit_scope: 'tokens_per_minute',
        rate_limit: { retry_after_seconds: Math.max(1, Math.ceil((this.resetAt - this.now()) / 1000)),
          tokens_remaining_minute: this.remaining }
      };
    }
    // Reserve locally so overlapping requests cannot all consume the same
    // observed provider headroom. A later provider header is authoritative.
    this.remaining -= estimateTokens;
    return null;
  }
}
