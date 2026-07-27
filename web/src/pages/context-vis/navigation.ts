export function scrollToContextVisElement(elementId: string): void {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.getElementById(elementId)?.scrollIntoView({
    behavior: reduced ? "auto" : "smooth",
    block: "center",
  });
}
