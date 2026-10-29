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
    { path: '/compare', name: 'compare', component: () => import('./pages/ComparePage.vue') },
    { path: '/annotate', name: 'annotate', component: () => import('./pages/AnnotatePage.vue') },
    {
      path: '/annotate/:menuId',
      name: 'annotate-menu',
      component: () => import('./pages/AnnotateEditorPage.vue'),
      props: true,
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
