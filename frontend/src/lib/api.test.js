// CRA's jsdom test environment doesn't polyfill these (real browsers do) — needed
// by streamChat's use of TextEncoder/TextDecoder for SSE byte-stream parsing.
import { TextEncoder, TextDecoder } from "util";
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

import { STATUS_META, BOARD_COLUMNS, streamChat } from "./api";

describe("STATUS_META / BOARD_COLUMNS consistency", () => {
  // These two must stay in sync: every status BOARD_COLUMNS can display needs a
  // label/color in STATUS_META, or the board renders an undefined badge silently.
  const boardStatuses = BOARD_COLUMNS.flatMap((c) => c.statuses);

  test("every status referenced by a board column has metadata", () => {
    for (const status of boardStatuses) {
      expect(STATUS_META[status]).toBeDefined();
    }
  });

  test("every status column key is unique", () => {
    const keys = BOARD_COLUMNS.map((c) => c.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

function fakeSseResponse(chunks) {
  let i = 0;
  return {
    body: {
      getReader() {
        return {
          read() {
            if (i >= chunks.length) {
              return Promise.resolve({ done: true, value: undefined });
            }
            const value = new TextEncoder().encode(chunks[i]);
            i += 1;
            return Promise.resolve({ done: false, value });
          },
        };
      },
    },
  };
}

describe("streamChat SSE frame parsing", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  test("delivers each delta to the callback in order", async () => {
    global.fetch.mockResolvedValue(
      fakeSseResponse([
        'data: {"delta":"Hel"}\n\n',
        'data: {"delta":"lo"}\n\n',
        'data: {"done":true}\n\n',
      ]),
    );
    const received = [];
    await streamChat("orchestrator", "hi", (delta) => received.push(delta));
    expect(received).toEqual(["Hel", "lo"]);
  });

  test("a chunk split mid-frame is buffered and parsed once complete", async () => {
    // Simulates a network chunk boundary landing in the middle of one SSE frame —
    // the buffering logic in streamChat must hold the partial frame, not drop it.
    global.fetch.mockResolvedValue(
      fakeSseResponse(['data: {"delta":"Hel', 'lo"}\n\n']),
    );
    const received = [];
    await streamChat("orchestrator", "hi", (delta) => received.push(delta));
    expect(received).toEqual(["Hello"]);
  });

  test("surfaces a backend error frame via the callback", async () => {
    global.fetch.mockResolvedValue(fakeSseResponse(['data: {"error":"boom"}\n\n']));
    const received = [];
    await streamChat("orchestrator", "hi", (delta) => received.push(delta));
    expect(received).toEqual(["\n[error: boom]"]);
  });
});
