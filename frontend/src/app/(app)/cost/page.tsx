import LivingInstrument from "@/components/instrument/LivingInstrument";

/**
 * Cost / make-vs-buy entry to THE LIVING INSTRUMENT. One canvas, no tabs: the
 * part in real 3D with the make-vs-buy decision orbiting it as live readouts and
 * a quantity scrubber you drag to flip the recommended process. Session-authed.
 */
export default function CostPage() {
  return <LivingInstrument focus="decision" />;
}
