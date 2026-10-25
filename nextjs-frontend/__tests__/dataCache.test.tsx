import { act, renderHook, waitFor } from "@testing-library/react";

import { clearCache, invalidate, useCached } from "@/lib/data-cache";

describe("useCached", () => {
  beforeEach(() => clearCache());

  it("fetches once and reuses the result when a tab is visited again", async () => {
    const fetcher = jest.fn().mockResolvedValue({ data: 1 });
    const first = renderHook(() => useCached("k", fetcher));
    await waitFor(() =>
      expect(first.result.current.result).toEqual({ data: 1 }),
    );
    first.unmount(); // switching tabs unmounts the content

    const second = renderHook(() => useCached("k", fetcher));
    expect(second.result.current.result).toEqual({ data: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refetches after the data is invalidated", async () => {
    const fetcher = jest
      .fn()
      .mockResolvedValueOnce({ data: "old" })
      .mockResolvedValueOnce({ data: "new" });
    const hook = renderHook(() => useCached("k", fetcher));
    await waitFor(() =>
      expect(hook.result.current.result).toEqual({ data: "old" }),
    );

    act(() => invalidate("k"));
    await waitFor(() =>
      expect(hook.result.current.result).toEqual({ data: "new" }),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("doesn't keep errors, so the next visit retries", async () => {
    const fetcher = jest
      .fn()
      .mockResolvedValueOnce({ message: "down" })
      .mockResolvedValueOnce({ data: "ok" });
    const first = renderHook(() => useCached("k", fetcher));
    await waitFor(() =>
      expect(first.result.current.result).toEqual({ message: "down" }),
    );
    first.unmount();

    const second = renderHook(() => useCached("k", fetcher));
    await waitFor(() =>
      expect(second.result.current.result).toEqual({ data: "ok" }),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
