import { Accordion, Button, Card, Group, SimpleGrid, Text } from '@mantine/core'
import {
  Activity,
  ArrowRight,
  Blocks,
  Check,
  CircleAlert,
  Hash,
  Heart,
  LockKeyhole,
  Rabbit,
  ShieldCheck,
  Sparkles,
  UsersRound,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { motion } from 'motion/react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import bunnyHero from '../../assets/bunny-home-hero.png'
import { useRoles, useStructure } from '../../api/queries'
import type { DashboardContext } from '../../app/AppShell'

type Accent = 'violet' | 'blue' | 'mint' | 'rose' | 'amber'

function QuickAction({ icon: Icon, title, description, action, accent, onClick }: {
  icon: LucideIcon
  title: string
  description: string
  action: string
  accent: Accent
  onClick: () => void
}) {
  return (
    <motion.button
      type="button"
      className={`bunny-quick-action bunny-accent-${accent}`}
      onClick={onClick}
      whileHover={{ y: -3 }}
      whileTap={{ scale: 0.99 }}
      transition={{ duration: 0.16 }}
    >
      <span className="bunny-quick-icon"><Icon size={24} strokeWidth={2.2} /></span>
      <strong>{title}</strong>
      <span>{description}</span>
      <span className="bunny-quick-link">{action}<ArrowRight size={15} /></span>
    </motion.button>
  )
}

export function OverviewScreen() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { me, guild, connection, capabilities } = useOutletContext<DashboardContext>()
  const structure = useStructure(me.user.discord_user_id, guild.guild_id)
  const roles = useRoles(me.user.discord_user_id, guild.guild_id)

  const channelCount = structure.data
    ? structure.data.root_channels.length + structure.data.categories.reduce((count, category) => count + category.channels.length, 0)
    : null
  const categoryCount = structure.data?.categories.length ?? null
  const roleCount = roles.data?.roles.length ?? null
  const decisions = Object.values(capabilities?.bot_operations ?? {})
  const blockedCount = decisions.filter((decision) => decision.outcome === 'CANNOT').length
  const checkingCount = decisions.filter((decision) => decision.outcome === 'UNKNOWN').length
  const hasDataError = structure.isError || roles.isError || connection === 'offline' || connection === 'unauthorized'
  const healthState = hasDataError || blockedCount > 0 ? 'attention' : !capabilities || checkingCount > 0 || connection === 'reconnecting' ? 'checking' : 'good'
  const userName = me.user.global_name ?? me.user.username

  const healthTitle = t(`home.health.${healthState}.title`, { count: blockedCount || checkingCount || 1 })
  const healthCopy = t(`home.health.${healthState}.copy`)
  const connectionText = connection === 'live' ? t('home.connection.online') : connection === 'unauthorized' ? t('home.connection.action') : t('home.connection.checking')

  const setupSteps = [
    { label: t('home.setup.identity'), copy: t('home.setup.identityCopy'), complete: true },
    { label: t('home.setup.structure'), copy: t('home.setup.structureCopy'), complete: Boolean(channelCount) },
    { label: t('home.setup.access'), copy: t('home.setup.accessCopy'), complete: Boolean(capabilities && blockedCount === 0) },
    { label: t('home.setup.automate'), copy: t('home.setup.automateCopy'), complete: false },
  ]

  return (
    <section className="bunny-home">
      <header className="bunny-home-heading">
        <div>
          <p className="bunny-page-eyebrow">{guild.name}</p>
          <h1>{t('home.title')}</h1>
          <p>{t('home.subtitle')}</p>
        </div>
      </header>

      <Card className="bunny-home-hero" padding={0} radius="xl" withBorder>
        <img src={bunnyHero} alt="" aria-hidden="true" />
        <div className="bunny-home-hero-overlay" />
        <div className="bunny-home-hero-copy">
          <span className="bunny-hero-kicker"><Rabbit size={17} />{t('home.welcome', { name: userName })}</span>
          <h2>{t('home.heroTitle')}</h2>
          <p>{t('home.heroCopy')}</p>
          <Group gap="sm" className="bunny-hero-actions">
            <Button size="md" variant="gradient" rightSection={<ArrowRight size={17} />} onClick={() => navigate(`/guild/${guild.guild_id}/structure`)}>
              {t('home.primaryAction')}
            </Button>
            <Button size="md" variant="white" color="dark" onClick={() => navigate(`/guild/${guild.guild_id}/policies`)}>
              {t('home.secondaryAction')}
            </Button>
          </Group>
        </div>
      </Card>

      <section className="bunny-home-section">
        <div className="bunny-section-heading">
          <div><h2>{t('home.quickTitle')}</h2><p>{t('home.quickSubtitle')}</p></div>
        </div>
        <SimpleGrid cols={{ base: 1, xs: 2, lg: 5 }} spacing="md">
          <QuickAction icon={Hash} title={t('home.action.channel')} description={t('home.action.channelCopy')} action={t('home.action.open')} accent="violet" onClick={() => navigate(`/guild/${guild.guild_id}/structure`)} />
          <QuickAction icon={ShieldCheck} title={t('home.action.access')} description={t('home.action.accessCopy')} action={t('home.action.open')} accent="mint" onClick={() => navigate(`/guild/${guild.guild_id}/policies`)} />
          <QuickAction icon={UsersRound} title={t('home.action.roles')} description={t('home.action.rolesCopy')} action={t('home.action.open')} accent="blue" onClick={() => navigate(`/guild/${guild.guild_id}/roles`)} />
          <QuickAction icon={Sparkles} title={t('home.action.automate')} description={t('home.action.automateCopy')} action={t('home.action.open')} accent="rose" onClick={() => navigate(`/guild/${guild.guild_id}/wizards`)} />
          <QuickAction icon={Activity} title={t('home.action.activity')} description={t('home.action.activityCopy')} action={t('home.action.open')} accent="amber" onClick={() => navigate(`/guild/${guild.guild_id}/plans`)} />
        </SimpleGrid>
      </section>

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg" className="bunny-home-lower">
        <Card className={`bunny-health-card state-${healthState}`} padding="lg" radius="xl" withBorder>
          <div className="bunny-card-heading">
            <div><h2>{t('home.healthTitle')}</h2><p>{t('home.healthSubtitle')}</p></div>
            <span className="bunny-health-symbol">{healthState === 'good' ? <Check /> : healthState === 'attention' ? <CircleAlert /> : <Sparkles />}</span>
          </div>
          <div className="bunny-health-message">
            <span>{healthState === 'good' ? <Heart size={22} /> : healthState === 'attention' ? <CircleAlert size={22} /> : <Sparkles size={22} />}</span>
            <div><strong>{healthTitle}</strong><p>{healthCopy}</p></div>
          </div>
          <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm" className="bunny-stat-grid">
            <button type="button" onClick={() => navigate(`/guild/${guild.guild_id}/structure`)}><span className="blue"><Hash size={18} /></span><strong>{channelCount ?? '—'}</strong><small>{t('home.stat.channels')}</small></button>
            <button type="button" onClick={() => navigate(`/guild/${guild.guild_id}/structure`)}><span className="violet"><Blocks size={18} /></span><strong>{categoryCount ?? '—'}</strong><small>{t('home.stat.categories')}</small></button>
            <button type="button" onClick={() => navigate(`/guild/${guild.guild_id}/roles`)}><span className="mint"><UsersRound size={18} /></span><strong>{roleCount ?? '—'}</strong><small>{t('home.stat.roles')}</small></button>
            <button type="button" onClick={() => navigate(`/guild/${guild.guild_id}/diagnostics`)}><span className="rose"><LockKeyhole size={18} /></span><strong>{connectionText}</strong><small>{t('home.stat.connection')}</small></button>
          </SimpleGrid>
          <Accordion className="bunny-technical-details" variant="separated" radius="md">
            <Accordion.Item value="technical">
              <Accordion.Control>{t('home.technicalDetails')}</Accordion.Control>
              <Accordion.Panel>
                <Text size="sm">{t('home.technicalSummary', { coverage: capabilities?.coverage ?? t('common.unknown'), freshness: capabilities?.freshness ?? t('common.unknown') })}</Text>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        </Card>

        <Card className="bunny-setup-card" padding="lg" radius="xl" withBorder>
          <div className="bunny-card-heading">
            <div><h2>{t('home.setupTitle')}</h2><p>{t('home.setupSubtitle')}</p></div>
            <span className="bunny-setup-icon"><Wrench size={21} /></span>
          </div>
          <ol className="bunny-setup-list">
            {setupSteps.map((step, index) => (
              <li key={step.label} className={step.complete ? 'complete' : ''}>
                <span>{step.complete ? <Check size={16} /> : index + 1}</span>
                <div><strong>{step.label}</strong><small>{step.copy}</small></div>
              </li>
            ))}
          </ol>
          <Button fullWidth mt="md" variant="light" rightSection={<ArrowRight size={16} />} onClick={() => navigate(`/guild/${guild.guild_id}/structure`)}>
            {t('home.continue')}
          </Button>
        </Card>
      </SimpleGrid>
    </section>
  )
}
