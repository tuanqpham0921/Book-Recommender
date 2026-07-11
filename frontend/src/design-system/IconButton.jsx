import { forwardRef } from 'react'

// Icon-only controls (thumbs up/down, close, report...). `tone` + `active`
// pick the accent when pressed/selected (e.g. a thumbs-up already recorded);
// unset stays neutral gray, matching the app's black & white default.
const TONE_CLASSES = {
    neutral: 'text-[var(--text-inactive)] bg-transparent hover:text-[var(--text-hover)] hover:bg-[var(--bg-tertiary)]',
    positive: 'text-[var(--accent-positive)] bg-[var(--accent-positive-bg)]',
    negative: 'text-[var(--accent-negative)] bg-[var(--accent-negative-bg)]',
    info: 'text-[var(--accent-info)] bg-[var(--accent-info-bg)]',
}

const IconButton = forwardRef(function IconButton(
    { tone = 'neutral', active = false, className = '', type = 'button', children, ...props },
    ref
) {
    const toneClass = active ? TONE_CLASSES[tone] : TONE_CLASSES.neutral
    return (
        <button
            ref={ref}
            type={type}
            className={`p-1.5 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${toneClass} ${className}`}
            {...props}
        >
            {children}
        </button>
    )
})

export default IconButton
