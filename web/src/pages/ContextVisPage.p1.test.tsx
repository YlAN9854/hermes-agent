// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "@/lib/api";
import ContextVisPage from "./ContextVisPage";
import {
  contextSessions,
  intentSegment,
  longUnbrokenTurn,
  observedCompression,
  reconstructedCompression,
  sessionDetail,
} from "./context-vis/test-fixtures";

const scrollIntoView = vi.fn();

beforeAll(() => {
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoView,
  });
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    })),
  });
});

afterEach(() => {
  cleanup();
  scrollIntoView.mockClear();
  vi.restoreAllMocks();
});

function renderPage(
  tierThree = sessionDetail("tier3", observedCompression),
  tierOne = sessionDetail("tier1", null),
) {
  vi.spyOn(api, "getContextVisSessions").mockResolvedValue(contextSessions);
  vi.spyOn(api, "getContextVisSession").mockImplementation(async (sessionId) => (
    sessionId === "tier3" ? tierThree : tierOne
  ));
  const save = vi.spyOn(api, "saveContextVisModel").mockImplementation(
    async (_sessionId, body) => ({
      model: {
        ...tierThree.model,
        revision: tierThree.model.revision + 1,
        intent_segments: [...(body.intent_segments ?? tierThree.model.intent_segments)],
      },
    }),
  );
  render(
    <MemoryRouter>
      <ContextVisPage />
    </MemoryRouter>,
  );
  return save;
}

describe("ContextVis Model/A lens", () => {
  it("labels synthetic context, keeps a live B anchor, and expands one contiguous dead-turn group", async () => {
    // Given
    renderPage();
    const modelToggle = await screen.findByRole("button", { name: "Model view" });

    // When
    fireEvent.click(modelToggle);

    // Then
    expect(screen.getByText(/Synthetic summary/)).toBeTruthy();
    expect(document.getElementById("cv-turn-t3")).toBeTruthy();
    const deadGroup = screen.getByRole("button", { name: /2 turns no longer in context/ });
    fireEvent.click(deadGroup);
    const unicodeText = screen.getByText(
      (_, element) => element?.tagName === "PRE" && element.textContent === "A😀𠜎é",
    );
    expect(unicodeText).toBeTruthy();
    expect(unicodeText.closest("pre")?.lang).toBe("zh");
    const liveText = screen.getByText(longUnbrokenTurn);
    expect(liveText.closest("pre")?.className).toContain("cv-turn-content");
  });

  it("shows reconstructed linkage uncertainty instead of claiming unlinked turns are certainly gone", async () => {
    // Given
    renderPage(sessionDetail("tier3", reconstructedCompression));

    // When
    fireEvent.click(await screen.findByRole("button", { name: "Model view" }));

    // Then
    expect(screen.getByRole("status", { name: "Model context uncertainty" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /3 turns not linked to reconstructed context/ })).toBeTruthy();
    expect(screen.queryByText(/never been compacted/)).toBeNull();
  });

  it("states the never-compacted and empty-transcript case without fabricating an event", async () => {
    // Given
    const detail = sessionDetail("tier3", {
      ...observedCompression,
      live_turn_ids: [],
      synthetic_entries: [],
      events: [],
    });
    detail.transcript = [];
    detail.model.units = [];
    renderPage(detail);

    // When
    fireEvent.click(await screen.findByRole("button", { name: "Model view" }));

    // Then
    expect(screen.getByText(/never been compacted/)).toBeTruthy();
    expect(screen.getByText("No transcript turns.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Compression events/ })).toBeNull();
  });

  it("normalizes Model view to Transcript when switching from Tier 3 to Tier 1", async () => {
    // Given
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Model view" }));

    // When
    fireEvent.click(screen.getByRole("button", { name: /Tier 3 observed/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Tier 1 sparse/ }));

    // Then
    await waitFor(() => expect(screen.queryByRole("button", { name: "Model view" })).toBeNull());
    expect(screen.getByRole("button", { name: "Transcript" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("No transcript turns.")).toBeTruthy();
  });
});

describe("ContextVis manual intent editing", () => {
  it("arms, cancels, captures a Unicode whole turn, saves with CAS, restores focus, and navigates to B", async () => {
    // Given
    const save = renderPage();
    const label = await screen.findByRole("textbox", { name: "New segment label" });
    fireEvent.change(label, { target: { value: "Research method pivot" } });
    fireEvent.change(screen.getByRole("combobox", { name: "New segment start" }), { target: { value: "u1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "New segment end" }), { target: { value: "u2" } });
    const arm = screen.getByRole("button", { name: "Arm new-segment trigger" });
    fireEvent.click(arm);
    fireEvent.click(screen.getByRole("button", { name: "Cancel new-segment trigger capture" }));

    // When
    fireEvent.click(screen.getByRole("button", { name: "Arm new-segment trigger" }));
    fireEvent.click(screen.getByRole("button", { name: /Select turn 1/ }));
    await waitFor(() => expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Arm new-segment trigger" }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Add intent segment" }));

    // Then
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith(
      "tier3",
      expect.objectContaining({
        revision: 7,
        intent_segments: [
          expect.objectContaining({
            label: "Research method pivot",
            from_unit_id: "u1",
            to_unit_id: "u2",
            trigger_span: { turn_id: "t1", char_start: 0, char_end: 5 },
          }),
        ],
      }),
      "",
    );
    expect((await screen.findByRole("status", { name: "Intent save status" })).textContent).toContain("revision 8");
    fireEvent.click(screen.getByRole("button", { name: "Go to trigger for Research method pivot" }));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("blocks an overlapping closed range on the client without sending a save", async () => {
    // Given
    const detail = sessionDetail("tier3", observedCompression, [intentSegment("existing")]);
    const save = renderPage(detail);
    fireEvent.change(await screen.findByRole("textbox", { name: "New segment label" }), { target: { value: "Overlap" } });
    fireEvent.change(screen.getByRole("combobox", { name: "New segment start" }), { target: { value: "u1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "New segment end" }), { target: { value: "u2" } });

    // When
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add intent segment" }));
    });

    // Then
    expect(screen.getByRole("alert").textContent).toContain("overlaps");
    expect(save).not.toHaveBeenCalled();
  });
});

describe("ContextVis narrow-screen controls", () => {
  it("exposes an expanded session dialog with a viewport-bounded width", async () => {
    // Given
    renderPage();
    const switcher = await screen.findByRole("button", { name: /Tier 3 observed/ });

    // When
    fireEvent.click(switcher);

    // Then
    expect(switcher.getAttribute("aria-expanded")).toBe("true");
    const dialog = screen.getByRole("dialog", { name: "Choose session" });
    expect(dialog.style.width).toBe("calc(100vw - 2rem)");
    expect(dialog.style.maxWidth).toBe("26rem");
    expect(document.querySelector(".cv-page-header")?.className).toContain("flex-wrap");
    expect(
      screen.getByRole("group", { name: "Conversation view" }).className,
    ).toContain("flex-wrap");
  });
});
