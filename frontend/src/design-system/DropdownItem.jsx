// One selectable row inside a Dropdown panel — the version list, category
// picker, and chat suggestions all render a list of these.
function DropdownItem({ selected = false, className = '', children, ...props }) {
    return (
        <button
            type="button"
            className={`block w-full px-3 py-2 text-left text-sm transition-colors hover:bg-[var(--bg-secondary)] ${selected ? 'bg-[var(--bg-secondary)] text-[var(--text-active)] font-medium' : 'text-[var(--text-hover)]'} ${className}`}
            {...props}
        >
            {children}
        </button>
    )
}

export default DropdownItem
