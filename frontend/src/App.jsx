import { useState } from 'react'
import UserPage from './pages/UserPage'
import DevPage  from './pages/DevPage'

export default function App() {
  const [lang, setLang] = useState(() => {
    const saved = window.localStorage.getItem('ui-lang')
    if (saved === 'zh' || saved === 'en') return saved
    return navigator.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en'
  })
  const [view, setView] = useState(
    window.location.hash === '#dev' ? 'dev' : 'user'
  )

  const switchView = (v) => {
    window.location.hash = v === 'dev' ? '#dev' : ''
    setView(v)
  }

  const toggleLang = () => {
    setLang((current) => {
      const next = current === 'zh' ? 'en' : 'zh'
      window.localStorage.setItem('ui-lang', next)
      return next
    })
  }

  return view === 'dev'
    ? <DevPage  lang={lang} onToggleLang={toggleLang} onSwitchToUser={() => switchView('user')} />
    : <UserPage lang={lang} onToggleLang={toggleLang} onSwitchToDev={() => switchView('dev')} />
}
