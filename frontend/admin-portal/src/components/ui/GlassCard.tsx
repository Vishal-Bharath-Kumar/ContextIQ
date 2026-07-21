import type { HTMLAttributes, ReactNode } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  className?: string;
  /** Delay (in ms) applied to the entrance animation — used to stagger grids of cards. */
  delay?: number;
}

/**
 * Reusable glassmorphism surface: translucent, blurred, soft-bordered card
 * used throughout the admin portal for consistent depth and elevation.
 */
export function GlassCard({ children, className = "", delay = 0, style, ...rest }: Props) {
  return (
    <div
      className={`glass-card animate-slide-up ${className}`}
      style={{ animationDelay: `${delay}ms`, ...style }}
      {...rest}
    >
      {children}
    </div>
  );
}
