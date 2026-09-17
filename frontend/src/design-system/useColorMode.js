import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'color-mode'

function readInitial() {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(STORAGE_KEY) === 'on'
}

// App-wide black & white <-> color switch. Setting data-color="on" on
// <html> flips every --accent-* variable in styles/tokens.css at once, so
// components never carry their own color-mode branching — they just read
// var(--accent-*) and this hook does the rest. Persisted so the choice
// survives a reload.
export function useColorMode() {
    const [enabled, setEnabled] = useState(readInitial)

    useEffect(() => {
        document.documentElement.dataset.color = enabled ? 'on' : 'off'
        window.localStorage.setItem(STORAGE_KEY, enabled ? 'on' : 'off')
    }, [enabled])

    const toggle = useCallback(() => setEnabled(prev => !prev), [])

    return [enabled, toggle]
}
