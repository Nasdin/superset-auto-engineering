export function safeUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? value
      : undefined;
  } catch {
    return undefined;
  }
}
