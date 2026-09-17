import { Palette } from 'lucide-react'
import { useColorMode } from './useColorMode'

// Single switch for the app's small amount of allowed color (book covers,
// like/dislike, status badges, errors) — everything else stays black &
// white regardless of this toggle.
function ColorModeToggle({ className = '' }) {
    const [enabled, toggle] = useColorMode()

    return (
        <button
            type="button"
            onClick={toggle}
            title={enabled ? 'Switch to black & white' : 'Add some color'}
            aria-pressed={enabled}
            className={`p-2 rounded-full transition-colors ${enabled ? 'text-[var(--accent-info)] bg-[var(--accent-info-bg)]' : 'text-[var(--text-inactive)] hover:bg-[var(--bg-tertiary)]'} ${className}`}
        >
            <Palette size={20} strokeWidth={1.5} />
        </button>
    )
}

export default ColorModeToggle
