interface InlineTextProps {
  text: string;
}

export function InlineText({ text }: InlineTextProps) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
          return (
            <code
              key={index}
              className="rounded bg-[#1B2233] border border-[#2A3347] px-1.5 py-0.5 font-mono text-[0.88em] text-blue-200"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={index}>{part}</span>;
      })}
    </>
  );
}
