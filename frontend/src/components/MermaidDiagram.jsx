import { useEffect, useRef, memo, useState } from 'react'
import mermaid from 'mermaid'
import Panzoom from "@panzoom/panzoom";

function MermaidDiagram({ chart }) {
    const containerRef = useRef(null)
    const lastChartRef = useRef('')
    const panzoomRef = useRef(null) // { instance, handler } of the active panzoom
    const [isLoading, setIsLoading] = useState(false)

    useEffect(() => {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'base',
            securityLevel: 'loose',
            themeVariables: {
                // px, not rem: mermaid does numeric math on this for label
                // sizing and misreads rem values
                fontSize: '14px',
                fontFamily: 'var(--font-sans)',
                primaryColor: '#f5f5f5',
                primaryTextColor: '#111',
                primaryBorderColor: '#111',
                lineColor: '#111',
                secondaryColor: '#e5e5e5',
                tertiaryColor: '#f9f9f9',
                clusterBkg: '#f5f5f5',
                clusterBorder: '#111',
                edgeLabelBackground: '#fff',
                nodeTextColor: '#111',
            },
            flowchart: {
                useMaxWidth: false,
                htmlLabels: false,
                curve: 'basis',
            },
        })

        const renderChart = async () => {
            if (!chart || chart === lastChartRef.current) return

            // Clear container first
            if (containerRef.current) {
                containerRef.current.innerHTML = ''
            }

            lastChartRef.current = chart
            let svgId = null

            setIsLoading(true)

            try {
                // Generate unique ID for each render
                svgId = `mermaid-${Date.now()}-${Math.random().toString(36).slice(2)}`

                const { svg } = await mermaid.render(svgId, chart)

                // Only update if container still exists
                if (containerRef.current) {
                    containerRef.current.innerHTML = svg

                    const svgElement = containerRef.current.querySelector('svg')
                    if (svgElement) {
                        // tear down the previous instance and its listener
                        // before wiring a new one
                        if (panzoomRef.current) {
                            containerRef.current.removeEventListener(
                                "wheel", panzoomRef.current.handler
                            )
                            panzoomRef.current.instance.destroy()
                        }

                        const panzoom = Panzoom(svgElement, {
                            maxScale: 10,
                            minScale: 0.75,  // don't let it shrink past 3/4
                            step: 0.20,     // gentler wheel zoom (default 0.3)
                            canvas: true,   // bind drag to the container (svg's parent),
                                            // not just the svg's own bounding box
                        });

                        // on the container so the whole framed area zooms the
                        // diagram; zoomWithWheel preventDefaults, which also
                        // keeps ctrl+wheel from zooming the browser here
                        const handler = panzoom.zoomWithWheel
                        containerRef.current.addEventListener(
                            "wheel", handler, { passive: false }
                        );
                        panzoomRef.current = { instance: panzoom, handler }
                    }
                }

            } catch (err) {
                console.error('Mermaid rendering error:', err)
                if (containerRef.current) {
                    containerRef.current.innerHTML = `<div class="text-[var(--accent-negative)] text-sm">Failed to render diagram</div>`
                }
            } finally {
                setIsLoading(false)

                // Clean up orphaned divs
                if (svgId){
                    console.log('Mermaid cleaning ID:', svgId)
                    const tempDiv = document.getElementById(`d${svgId}`)
                    if (tempDiv && tempDiv.parentNode) {
                        tempDiv.parentNode.removeChild(tempDiv)
                    }
                } else {
                    console.error('Mermaid no svg ID to clean')
                }
                // const orphans = document.querySelectorAll('div[id^="dmermaid-"]');
                // orphans.forEach(div => div.remove());
                // Clean up the specific temporary div created by mermaid
            }
        }

        renderChart()

        const container = containerRef.current
        return () => {
            if (panzoomRef.current) {
                container?.removeEventListener(
                    "wheel", panzoomRef.current.handler
                )
                panzoomRef.current.instance.destroy()
                panzoomRef.current = null
            }
        }
    }, [chart])

    return (
        <div className="mermaid-container relative">

            <button
                type="button"
                onClick={() => panzoomRef.current?.instance.reset()}
                title="Reset view"
                className="absolute bottom-2 right-2 z-10 px-2 py-1 rounded-md text-sm bg-[var(--bg-primary)]/80 text-[var(--text-inactive)] hover:text-[var(--text-active)] hover:bg-[var(--bg-primary)] transition-colors"
            >
                ↺ Reset
            </button>

            {isLoading && (
                <div className="loading-wrapper">
                    {/* <div className="loading-spinner" /> */}
                    <span className="loading-text">Rendering Mermaid Diagram...</span>
                </div>
            )}

            <div ref={containerRef} className="mermaid-svg" />

        </div>
    )
}

export default memo(MermaidDiagram)
