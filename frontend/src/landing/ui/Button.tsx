import type { ReactNode } from "react";

export function Button({
  href,
  variant = "primary",
  children,
}: {
  href: string;
  variant?: "primary" | "ghost";
  children: ReactNode;
}) {
  return (
    <a href={href} className={`btn btn--${variant}`}>
      {children}
    </a>
  );
}
