import {Directive, HostListener, OnInit, ElementRef, inject, input} from '@angular/core';

@Directive({
  // eslint-disable-next-line @angular-eslint/directive-selector
  selector: '[a11y-click]',
  standalone: true
})
export class A11yClickDirective implements OnInit {
  private element = inject<ElementRef>(ElementRef);

  keyCodes = input.required<string>({alias: 'a11y-click'})
  keyCodeArray!: string[];

  ngOnInit(){
    if(this.keyCodes()) {
      this.keyCodeArray = this.keyCodes().split(',');
    }
  }

  @HostListener('keydown', ['$event'])
  onEvent(event: any) {
    const keyCodeCondition = () => {
      let flag = false;
      if (!(event.keyCode)) {
        if (event.which) {
          event.keyCode = event.which;
        } else if (event.charCode) {
          event.keyCode = event.charCode;
        }
      }
      if ((event.keyCode && this.keyCodeArray.indexOf(event.keyCode.toString()) > -1)) {
        flag = true;
      }
      return flag;
    };
    if (this.keyCodeArray.length > 0 && keyCodeCondition()) {
      this.element.nativeElement.click();
      event.preventDefault();
    }

  }

}
