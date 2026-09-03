"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useSecuritySearch } from "@/lib/api/hooks";
import { MIN_SEARCH_LENGTH } from "@/lib/api/securities";
import type { SecurityRead } from "@/lib/api/types";
import { securityHref } from "@/lib/format";

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

type Variant = "hero" | "bar";

const PLACEHOLDER: Record<Variant, string> = {
  hero: "Search ticker or company — e.g. NVDA, Apple",
  bar: "Search ticker or company",
};

export function SecuritySearch({ variant = "hero" }: { variant?: Variant }) {
  const router = useRouter();
  const baseId = useId();
  const listId = `${baseId}-list`;
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1);
  const blurTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const debounced = useDebounced(text.trim(), 250);
  const query = useSecuritySearch(debounced);
  const results: SecurityRead[] = query.data?.results ?? [];

  const open = focused && text.trim().length >= MIN_SEARCH_LENGTH;
  const showResults = open && query.isSuccess && results.length > 0;
  const showNoResults = open && query.isSuccess && results.length === 0;

  useEffect(() => setActive(-1), [debounced]);
  useEffect(() => () => { if (blurTimer.current) clearTimeout(blurTimer.current); }, []);

  function navigate(security: SecurityRead) {
    router.push(securityHref(security.ticker));
    setFocused(false);
    setText("");
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setText("");
      setFocused(false);
      return;
    }
    if (!showResults) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(results.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter" && active >= 0 && results[active]) {
      event.preventDefault();
      navigate(results[active]);
    }
  }

  return (
    <div className={`qs-search qs-search--${variant}`}>
      <label className="qs-search__label" htmlFor={`${baseId}-input`}>
        Search securities by ticker or name
      </label>
      <input
        id={`${baseId}-input`}
        className="qs-search__input"
        type="search"
        autoComplete="off"
        autoFocus={variant === "hero"}
        placeholder={PLACEHOLDER[variant]}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => {
          if (blurTimer.current) clearTimeout(blurTimer.current);
          setFocused(true);
        }}
        onBlur={() => {
          blurTimer.current = setTimeout(() => setFocused(false), 120);
        }}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${baseId}-opt-${active}` : undefined}
      />

      {open && (
        <div className="qs-search__panel">
          {query.isLoading && (
            <div className="qs-search__loading" aria-live="polite" aria-label="Searching">
              <span className="qs-skel" />
              <span className="qs-skel" />
            </div>
          )}

          {query.isError && (
            <div className="qs-search__msg qs-search__msg--error" role="alert">
              Couldn&rsquo;t reach the search service. Please try again.
              <div>
                <button type="button" className="qs-retry" onClick={() => query.refetch()}>
                  Retry
                </button>
              </div>
            </div>
          )}

          {showNoResults && (
            <div className="qs-search__msg">No securities match this search.</div>
          )}

          {showResults && (
            <ul id={listId} role="listbox" aria-label="Search results" style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {results.map((s, i) => (
                <li key={s.ticker} role="presentation">
                  <Link
                    id={`${baseId}-opt-${i}`}
                    role="option"
                    aria-selected={i === active}
                    className="qs-result"
                    href={securityHref(s.ticker)}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => {
                      setFocused(false);
                      setText("");
                    }}
                  >
                    <span>
                      <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                        <span className="qs-result__ticker">{s.ticker}</span>
                        {!s.is_active && <span className="qs-badge-inactive">INACTIVE</span>}
                      </span>
                      <span className="qs-result__name">{s.name}</span>
                    </span>
                    <span className="qs-result__meta">{s.exchange}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
