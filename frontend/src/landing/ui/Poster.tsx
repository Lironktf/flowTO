import { TowerPoster } from "./posters/TowerPoster";
import { TrophyPoster } from "./posters/TrophyPoster";

/** Dispatches to the per-artifact poster. Each poster file is owned by its
 * section agent (Tower → Hero agent, Trophy → Trophy agent). */
export function Poster({ variant }: { variant: "tower" | "trophy" }) {
  return variant === "tower" ? <TowerPoster /> : <TrophyPoster />;
}
