from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import numpy as np


class Scenario:
    def __init__(self, capital, housing_budget, monthly_rent, house_price, downpayment,
                 housing_gr_rate, rent_gr_rate, mortgage_rate, return_rate,
                 horizon=25*12):
        self.today = datetime.now().date()
        self.initial_capital = capital
        self.horizon = horizon
        self.rent = self.create_monthly_series(monthly_rent, self.today, rent_gr_rate)
        self.housing_budget = self.create_monthly_series(housing_budget, self.today, 
                                                         housing_gr_rate)
        self.house_price = house_price
        self.downpayment = downpayment
        self.housing_gr_rate = housing_gr_rate
        self.rent_gr_rate = rent_gr_rate
        self.mortgage_rate = mortgage_rate
        self.return_rate = return_rate
        self.monthly_rate = self.compute_monthly_rate(self.return_rate)
        self.monthly_housing_gr_rate = self.compute_monthly_rate(self.housing_gr_rate)
        self.monthly_mortgage_rate = self.compute_monthly_rate(self.mortgage_rate)
        self.check_data()
        self.municipal_taxes = {}

    def check_data(self):
        assert self.downpayment <= self.initial_capital, f'downpayment > initial capital ({self.downpayment} > {self.initial_capital})'
        ratio = self.downpayment / self.house_price
        assert ratio >= 0.2, f'Downpayment is less than 20% of house price (only {ratio * 100:.2f}%)'
        
    def simulate_renting(self):
        self.capital = Asset(self.initial_capital, self.monthly_rate, self.today)
        for n_months in range(self.horizon):
            date = self.today + relativedelta(months=n_months)
            amount_available = self.capital.value[date] + self.housing_budget[date]
            current_rent = self.rent[date]
            assert current_rent <= amount_available, (
                f'rent too expensive: rent is {current_rent}',
                f'and housing budget + remaining capital is {amount_available}')
            if current_rent <= self.housing_budget[date]:
                self.capital.invest(self.housing_budget[date] - current_rent)
            else:
                self.capital.withdraw(current_rent - self.housing_budget[date])
            self.capital.update()
        
    def simulate_buying(self):
        self.capital = Asset(self.initial_capital, self.monthly_rate, self.today)
        self.capital.withdraw(self.downpayment)
        self.house = Asset(self.house_price, self.monthly_housing_gr_rate, self.today)
        self.mortgage = Mortgage(self.house_price - self.downpayment,
                                 self.monthly_mortgage_rate,
                                 self.horizon,
                                 self.today)
        self.mortgage.compute_payment()
        self.compute_transfer_tax()
        self.capital.withdraw(self.transfer_tax)

        for n_months in range(self.horizon):
            date = self.today + relativedelta(months=n_months)
            self.compute_municipal_taxes(date)
            amount_available = self.capital.value[date] + self.housing_budget[date]
            amount_to_pay = self.mortgage.monthly_payment + self.municipal_taxes[date]
            assert self.mortgage.monthly_payment <= amount_available, (
                f'mortgage too expensive: payment is {amount_to_pay}',
                f'and housing budget + remaining capital is {amount_available}')
            if amount_to_pay <= self.housing_budget[date]:
                self.capital.invest(self.housing_budget[date] - amount_to_pay)
            else:
                self.capital.withdraw(amount_to_pay - self.housing_budget[date])
            self.capital.update()
            self.mortgage.update()
            self.house.update()
            self.compute_net_asset_position()

    def compute_net_asset_position(self):
        self.net_asset_position = {
            date: self.capital.value[date] + self.house.value[date] - self.mortgage.value[date]
            for date in self.capital.value.keys()}

    def compute_monthly_rate(self, yearly_rate):
        return (1 + yearly_rate)**(1/12) - 1

    def create_monthly_series(self, initial_value, initial_date, yearly_rate):
        """"Amount adjusted by yearly_rate every 12 months"""
        return {initial_date + relativedelta(months=n_months):
                initial_value * (1 + yearly_rate)**int(n_months/12)
                for n_months in range(self.horizon)}

    def compute_transfer_tax(self):
        """for Mtl, 
        from http://equipemckenzie.com/outils/calcul-de-taxe-de-bienvenue"""
        cutoffs = [0, 50e3, 250e3, 500e3, 1e6, np.inf]
        rates = [0.005, 0.01, 0.015, 0.02, 0.025]

        amount = 0
        for i, rate in enumerate(rates):
            lower_cutoff, upper_cutoff = cutoffs[i], cutoffs[i+1]
            if self.house_price > lower_cutoff:
                amount += rate * (min(self.house_price, upper_cutoff) - lower_cutoff)
            else:
                break
        self.transfer_tax = amount
    
    def compute_municipal_taxes(self, date):
        """for Mtl in 2022, to be checked"""
        taxe_fonciere_generale = 0.005712
        taux_dettes_anciennes_villes = 0.000281
        taxe_speciale_eau = 0.000975
        taxe_relative_ARTM = 0.000023

        rate = (taxe_fonciere_generale + 
                taux_dettes_anciennes_villes +
                taxe_speciale_eau +
                taxe_relative_ARTM)
        self.municipal_taxes[date] = rate * self.house.value[date]


class Asset:
    def __init__(self, initial_value, monthly_rate, initial_date):
        self.date = initial_date
        self.value = {initial_date: initial_value}
        self.monthly_rate = monthly_rate

    def withdraw(self, amount):
        extra = amount - self.value[self.date]
        assert self.value[self.date] >= amount, f'insufficient capital, need an extra ${extra}'
        self.value[self.date] -= amount

    def invest(self, amount):
        self.value[self.date] += amount

    def update(self):
        next_date = self.date + relativedelta(months=1)
        self.value[next_date] = self.value[self.date] * (1 + self.monthly_rate)
        self.date = next_date

class Mortgage:
    def __init__(self, initial_value, monthly_rate, duration, initial_date):
        self.initial_date = initial_date
        self.date = initial_date
        self.monthly_rate = monthly_rate
        self.initial_value = initial_value
        self.value = {initial_date: initial_value}
        self.duration = duration

    def compute_payment(self):
        discount_factor = 1 / (1 + self.monthly_rate)
        coeff = (1 - discount_factor**self.duration) / (1 - discount_factor)
        # coeff = (1 + self.monthly_rate) / self.monthly_rate * (1 - (1 / (1 + self.monthly_rate))**self.duration)
        self.monthly_payment = self.initial_value / coeff

    def update(self):
        self.value[self.date] -= self.monthly_payment
        next_date = self.date + relativedelta(months=1)
        self.value[next_date] = self.value[self.date] * (1 + self.monthly_rate) 
        self.date = next_date