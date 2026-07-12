// Emoji render as full-color glyphs in most browsers/fonts — `color` can't
// touch them, only `filter` can. Wrapping one here ties it to the same
// monochrome/color switch as book covers (--mono-filter in
// styles/tokens.css): grayscale by default, full color once
// ColorModeToggle is on.
function Emoji({ children, className = '', ...props }) {
    return (
        <span className={`inline-block ${className}`} style={{ filter: 'var(--mono-filter)' }} {...props}>
            {children}
        </span>
    )
}

export default Emoji
