import { motion } from "framer-motion";
import type { ReactNode } from "react";

/** Scroll-reveal wrapper. Respects reduced-motion via the app's MotionConfig. */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, delay, ease: [0.4, 0, 0.1, 1] }}
    >
      {children}
    </motion.div>
  );
}
