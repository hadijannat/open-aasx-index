import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { HomePage } from './pages/HomePage'
import { AssetPage } from './pages/AssetPage'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/asset/:id" element={<AssetPage />} />
      </Routes>
    </Layout>
  )
}

export default App
