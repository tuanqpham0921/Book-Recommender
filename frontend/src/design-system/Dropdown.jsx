import { useCallback, useRef, useState } from 'react'
import { useOutsideClick } from '@/hooks/useOutsideClick'

// Generic dropdown shell — owns open/close state and outside-click-to-close,
// leaves the trigger and panel content entirely to the caller. Every
// dropdown-like control in the app (version picker, category picker, chat
// input suggestions) is built on this instead of re-implementing the same
// useState + useRef + outside-click effect.
//
// Uncontrolled by default (its own open state); pass `open`/`onOpenChange`
// to drive it externally instead (e.g. a control outside the dropdown, like
// the input box's focus handler, also needs to close it).
function Dropdown({
    trigger,
    children,
    align = 'left',
    placement = 'bottom',
    open: controlledOpen,
    onOpenChange,
    panelClassName = '',
    className = '',
}) {
    const [internalOpen, setInternalOpen] = useState(false)
    const isControlled = controlledOpen !== undefined
    const isOpen = isControlled ? controlledOpen : internalOpen
    const containerRef = useRef(null)

    const setOpen = useCallback((next) => {
        if (isControlled) onOpenChange?.(next)
        else setInternalOpen(next)
    }, [isControlled, onOpenChange])

    const toggle = useCallback(() => setOpen(!isOpen), [isOpen, setOpen])
    const close = useCallback(() => setOpen(false), [setOpen])

    useOutsideClick(containerRef, close, isOpen)

    return (
        <div className={`relative inline-block ${className}`} ref={containerRef}>
            {trigger({ isOpen, toggle, open: () => setOpen(true), close })}

            {isOpen && (
                <div
                    className={`absolute ${placement === 'top' ? 'bottom-full mb-1' : 'top-full mt-1'} ${align === 'right' ? 'right-0' : 'left-0'} bg-[var(--bg-primary)] border border-[var(--border-light)] rounded-lg shadow-lg z-50 overflow-hidden ${panelClassName}`}
                >
                    {typeof children === 'function' ? children({ close }) : children}
                </div>
            )}
        </div>
    )
}

export default Dropdown
