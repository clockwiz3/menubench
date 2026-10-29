import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'runs', component: () => import('./pages/RunsPage.vue') },
    { path: '/runs/:runId', name: 'run', component: () => import('./pages/RunPage.vue'), props: true },
    {
      path: '/runs/:runId/menus/:menuId',
      name: 'review',
      component: () => import('./pages/MenuReviewPage.vue'),
      props: true,
    },
    {
      path: '/annotate',
      name: 'annotate',
      component: () => import('./pages/PlaceholderPage.vue'),
      props: { title: 'Annotate' },
    },
    {
      path: '/try',
      name: 'try',
      component: () => import('./pages/PlaceholderPage.vue'),
      props: { title: 'Try it' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
