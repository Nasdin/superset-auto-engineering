import { ExternalLink } from "lucide-react";
import { safeUrl } from "../links";

export function External({
  url,
  children,
}: {
  url: string;
  children: React.ReactNode;
}) {
  const href = safeUrl(url);
  return href ? (
    <a className="button" href={href} target="_blank" rel="noreferrer">
      {children}
      <ExternalLink size={12} />
    </a>
  ) : (
    <span>Unavailable link</span>
  );
}
