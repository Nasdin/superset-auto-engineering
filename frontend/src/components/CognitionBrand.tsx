/** Vector wordmark stays crisp in the sidebar and on high-density displays. */
export function CognitionBrand() {
  return (
    <div className="cognition-brand" aria-label="Cognition">
      <svg
        viewBox="0 0 40 26"
        width="36"
        height="26"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M20 13 13.5 6.5a7 7 0 1 0 0 13L26.5 6.5a7 7 0 1 1 0 13L20 13"
          stroke="currentColor"
          strokeWidth="4.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>Cognition</span>
    </div>
  );
}
