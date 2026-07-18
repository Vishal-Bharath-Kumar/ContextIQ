import "@testing-library/jest-dom";

// Radix UI primitives (e.g. Slider, Accordion) use ResizeObserver internally.
// jsdom does not implement it, so we provide a no-op stub for all tests.
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
