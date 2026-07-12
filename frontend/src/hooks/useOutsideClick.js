import { useEffect } from 'react'

// Calls `handler` on the first mousedown outside every element referenced in
// `refs` (a single ref or an array of refs) — every dropdown panel, popover
// and modal in the app shares this instead of re-implementing it.
export function useOutsideClick(refs, handler, active = true) {
    useEffect(() => {
        if (!active) return

        const refList = Array.isArray(refs) ? refs : [refs]

        function handlePointerDown(event) {
            const isInside = refList.some(ref => ref.current && ref.current.contains(event.target))
            if (!isInside) handler(event)
        }

        document.addEventListener('mousedown', handlePointerDown)
        return () => document.removeEventListener('mousedown', handlePointerDown)
    }, [refs, handler, active])
}
