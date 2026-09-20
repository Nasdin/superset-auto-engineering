import { useEffect, useRef, type ReactNode } from "react";
import { ChevronDown, SlidersHorizontal, X } from "lucide-react";

/** Native disclosure preserves keyboard behavior and stays open during polling. */
export function Disclosure({
  title,
  summary,
  children,
  className = "",
}: {
  title: string;
  summary?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={`disclosure ${className}`}>
      <summary>
        <SlidersHorizontal size={16} aria-hidden="true" />
        <span className="disclosure-title">{title}</span>
        {summary && <span className="disclosure-summary">{summary}</span>}
        <ChevronDown
          className="disclosure-chevron"
          size={16}
          aria-hidden="true"
        />
      </summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}

/** Only mounting a user-selected record moves focus, never a polling refresh. */
export function Inspection({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const region = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!trigger.current) {
      trigger.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
    }
    region.current?.focus({ preventScroll: true });
    region.current?.scrollIntoView({ block: "start", behavior: "instant" });
  }, []);
  return (
    <section
      className="inspection"
      aria-label={title}
      ref={region}
      tabIndex={-1}
    >
      <div className="inspection-bar">
        <span>{title}</span>
        <button
          className="button"
          onClick={() => {
            onClose();
            if (trigger.current?.isConnected) trigger.current.focus();
          }}
        >
          <X size={14} />
          Close details
        </button>
      </div>
      {children}
    </section>
  );
}
