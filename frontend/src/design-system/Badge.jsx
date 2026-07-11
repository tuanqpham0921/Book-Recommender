// Small status pill — reused for run status ("ok"/"failed"), feedback
// state (liked/disliked/report), and issue categories. `tone` maps to the
// --accent-* tokens, so it's gray by default and only colors up when
// color mode is on.
const TONE_CLASSES = {
    neutral: 'bg-[var(--bg-tertiary)] text-[var(--text-inactive)]',
    positive: 'bg-[var(--accent-positive-bg)] text-[var(--accent-positive)]',
    negative: 'bg-[var(--accent-negative-bg)] text-[var(--accent-negative)]',
    warning: 'bg-[var(--accent-warning-bg)] text-[var(--accent-warning)]',
    info: 'bg-[var(--accent-info-bg)] text-[var(--accent-info)]',
}

function Badge({ tone = 'neutral', className = '', children, ...props }) {
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs whitespace-nowrap ${TONE_CLASSES[tone]} ${className}`} {...props}>
            {children}
        </span>
    )
}

export default Badge
