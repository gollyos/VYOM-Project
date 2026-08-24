/**
 * The VYOM brand mark: one core node, three orbiting satellites, and the
 * synapses between them - the same living-network idea as the biome,
 * distilled into a glyph that stays legible at 20px. The orbit is slow
 * and constant: an identity, not an alarm. Colors follow the state so
 * even the wordmark breathes with the machine.
 */
import { useId } from "react";
import { STATE_VISUALS, type VyomState } from "@/core/vyom-state";

export function BrandMark({ state, size = 22 }: { state: VyomState; size?: number }) {
  const visual = STATE_VISUALS[state];
  const gradientId = useId();
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      style={{ ["--mark-color" as string]: visual.color }}
    >
      <defs>
        <radialGradient id={`${gradientId}-core`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--mark-color)" stopOpacity="0.95" />
          <stop offset="55%" stopColor="var(--mark-color)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--mark-color)" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* halo */}
      <circle cx="24" cy="24" r="15" fill={`url(#${gradientId}-core)`} className="brand-halo" />

      {/* orbit paths */}
      <circle cx="24" cy="24" r="14.5" stroke="var(--mark-color)" strokeOpacity="0.28" strokeWidth="0.7" />
      <circle cx="24" cy="24" r="9" stroke="var(--mark-color)" strokeOpacity="0.18" strokeWidth="0.6" />

      {/* core */}
      <circle cx="24" cy="24" r="3.4" fill="var(--mark-color)" className="brand-core" />

      {/* orbiting satellites + synapses */}
      <g className="brand-orbit">
        <circle cx="24" cy="9.5" r="2" fill="var(--mark-color)" />
        <line x1="24" y1="12.5" x2="24" y2="20.6" stroke="var(--mark-color)" strokeOpacity="0.5" strokeWidth="0.8" />
      </g>
      <g className="brand-orbit brand-orbit-slow">
        <circle cx="37" cy="31.5" r="1.6" fill="var(--mark-color)" fillOpacity="0.9" />
        <line x1="35.3" y1="30" x2="26.8" y2="25.6" stroke="var(--mark-color)" strokeOpacity="0.4" strokeWidth="0.7" />
      </g>
      <g className="brand-orbit brand-orbit-reverse">
        <circle cx="11" cy="31.5" r="1.6" fill="var(--mark-color)" fillOpacity="0.9" />
        <line x1="12.7" y1="30" x2="21.2" y2="25.6" stroke="var(--mark-color)" strokeOpacity="0.4" strokeWidth="0.7" />
      </g>
    </svg>
  );
}
