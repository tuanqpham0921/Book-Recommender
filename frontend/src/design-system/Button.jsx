import { forwardRef } from 'react'

// Shared button styles for the whole app — swap a variant/size here rather
// than hand-rolling `bg-gray-800 text-white ...` at each call site. Colors
// are all CSS variables from styles/tokens.css, so retuning the palette
// there updates every button.
const VARIANT_CLASSES = {
    primary: 'bg-[var(--btn-primary-bg)] text-[var(--bg-primary)] border border-transparent hover:bg-[var(--btn-primary-hover)]',
    secondary: 'bg-[var(--btn-secondary-bg)] text-[var(--text-hover)] border border-[var(--btn-secondary-border)] hover:bg-[var(--btn-secondary-hover)]',
    ghost: 'bg-transparent text-[var(--text-inactive)] border border-transparent hover:text-[var(--text-hover)] hover:bg-[var(--bg-tertiary)]',
}

// Toggle/filter buttons (e.g. an active sort, filter, or issue/praise
// choice) swap to one of these accent tones — with a shadow so the
// selected state reads as "pressed", not just recolored — instead of
// their normal variant while active. Defaults to `info` so existing
// active-toggle call sites are unaffected by adding this prop.
const ACTIVE_TONE_CLASSES = {
    info: 'bg-[var(--accent-info-bg)] border border-[var(--accent-info-border)] text-[var(--accent-info)] shadow-sm',
    positive: 'bg-[var(--accent-positive-bg)] border border-[var(--accent-positive-border)] text-[var(--accent-positive)] shadow-sm',
    negative: 'bg-[var(--accent-negative-bg)] border border-[var(--accent-negative-border)] text-[var(--accent-negative)] shadow-sm',
    warning: 'bg-[var(--accent-warning-bg)] border border-[var(--accent-warning-border)] text-[var(--accent-warning)] shadow-sm',
}

const SIZE_CLASSES = {
    sm: 'px-2 py-1 text-xs',
    md: 'px-3 py-1.5 text-sm',
}

const Button = forwardRef(function Button(
    { variant = 'secondary', size = 'md', active = false, tone = 'info', className = '', type = 'button', children, ...props },
    ref
) {
    const toneClasses = active ? ACTIVE_TONE_CLASSES[tone] : VARIANT_CLASSES[variant]
    return (
        <button
            ref={ref}
            type={type}
            className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${SIZE_CLASSES[size]} ${toneClasses} ${className}`}
            {...props}
        >
            {children}
        </button>
    )
})

export default Button
