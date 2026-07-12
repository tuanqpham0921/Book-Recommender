import { useEffect } from 'react'
import { X } from 'lucide-react'
import IconButton from './IconButton'

// Generic overlay dialog — a bottom sheet on phones (slides up, thumb
// reachable), a centered dialog from `sm:` up. Reused for anything that
// needs "more info than fits inline" (book details, issue reports, ...).
function Modal({ isOpen, onClose, title, children, className = '' }) {
    useEffect(() => {
        if (!isOpen) return
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [isOpen, onClose])

    if (!isOpen) return null

    return (
        <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs z-50 flex items-end sm:items-center justify-center"
            onClick={onClose}
        >
            <div
                className={`bg-[var(--bg-primary)] w-full sm:max-w-lg rounded-t-2xl sm:rounded-2xl shadow-2xl max-h-[85vh] flex flex-col animate-slide-up sm:animate-none ${className}`}
                onClick={(event) => event.stopPropagation()}
            >
                <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--border-light)] flex-shrink-0">
                    <h2 className="font-semibold text-[var(--text-active)] line-clamp-2">{title}</h2>
                    <IconButton onClick={onClose} className="flex-shrink-0">
                        <X size={18} />
                    </IconButton>
                </div>

                <div className="px-5 py-4 overflow-y-auto flex-1">
                    {children}
                </div>
            </div>
        </div>
    )
}

export default Modal
