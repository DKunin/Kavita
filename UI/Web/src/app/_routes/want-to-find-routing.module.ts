import {Routes} from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'title.want-to-find',
    loadComponent: () => import('../want-to-find/want-to-find.component').then(c => c.WantToFindComponent)
  }
];
