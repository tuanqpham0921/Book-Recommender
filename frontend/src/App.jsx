import '@/index.css'
import { useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import BookRecommenderPage from '@/pages/BookRecommenderPage'
import api from '@/api'

function App() {
  // TODO: add a server not available page or message
  useEffect(() => {
    const checkBackendHealth = async () => {
      const res = await api.backEndPing()
      console.log(res)
    }
    checkBackendHealth()
  }, [])


  return (
    <Router>
      <Routes>
        <Route path="/" element={<BookRecommenderPage />} />
        <Route path="/blog" element={<BookRecommenderPage />} />
        <Route path="/review" element={<BookRecommenderPage />} />
        {/* Catch all other routes and redirect to home */}
        <Route path="*" element={<BookRecommenderPage />} />
      </Routes>
    </Router>
  )
}

export default App
