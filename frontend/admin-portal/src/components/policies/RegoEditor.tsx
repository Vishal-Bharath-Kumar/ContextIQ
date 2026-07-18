import { useEffect, useRef, useCallback } from "react";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { defaultKeymap, historyKeymap, history } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  ariaLabel?: string;
}

export function RegoEditor({ value, onChange, readOnly = false, ariaLabel }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);

  const onChangeCallback = useCallback(onChange, [onChange]);

  useEffect(() => {
    if (!containerRef.current) return;

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        onChangeCallback(update.state.doc.toString());
      }
    });

    const extensions: Extension[] = [
      history(),
      lineNumbers(),
      syntaxHighlighting(defaultHighlightStyle),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      updateListener,
      EditorView.editable.of(!readOnly),
      EditorView.contentAttributes.of({
        "aria-label": ariaLabel ?? "Rego policy editor",
        "aria-multiline": "true",
        role: "textbox",
      }),
    ];

    const state = EditorState.create({
      doc: value,
      extensions,
    });

    viewRef.current = new EditorView({
      state,
      parent: containerRef.current,
    });

    return () => {
      viewRef.current?.destroy();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Mount once; value updates handled below

  // Sync external value changes (e.g. loading a version)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return (
    <div
      ref={containerRef}
      className="border rounded font-mono text-sm min-h-[400px] focus-within:ring-2 focus-within:ring-blue-500"
      data-testid="rego-editor"
    />
  );
}
