from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import os
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from fake_useragent import UserAgent

class UpWorkJobScraper:

    def __init__(self):
        '''Initialize the scraper with dynamic user-agent and set up the WebDriver.'''
        self.driver = self.setup_webdriver()

    def setup_webdriver(self):
        '''Set up the Chrome WebDriver with necessary options for headless browsing and random user-agent.'''
        ua = UserAgent()
        user_agent = ua.random

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")  # Enable GPU support in headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f'--user-agent={user_agent}')

        driver = webdriver.Chrome(options=options)
        return driver
    
    def scraping(self, URL):
        '''Scrape job listings from Upwork based on the provided URL.'''
        self.driver.get(URL)
        self.data = []

        try:
            # Wait for the job titles to be loaded before proceeding
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, '//*[@id="air3-line-clamp-2"]/h2')) 
            )
        except TimeoutException:
            print("Loading took too much time!")
            self.driver.quit()
            return
     
        self.page_source = self.driver.page_source
        self.driver.quit()

        # Parse the page source using BeautifulSoup
        self.soup = BeautifulSoup(self.page_source, "html.parser")
        self.articles = self.soup.find_all('article', class_='job-tile cursor-pointer px-md-4 air3-card air3-card-list px-4x')
        
        # Extract job details from each article
        for article in self.articles:
            self.job_titles = article.find('h2', class_='h5 mb-0 mr-2 job-tile-title')
            self.posted_at = article.find('small', class_='text-light mb-1')
            self.payment_info = article.find('ul', class_='job-tile-info-list text-base-sm mb-4')
            self.link = article.find('a', class_='up-n-link')

            self.data.append({
                'Job title': self.job_titles.getText() if self.job_titles else 'Data not found',
                'Posted': self.posted_at.getText() if self.posted_at else 'Data not found',
                'Payment info': self.payment_info.getText() if self.payment_info else 'Data not found',
                'Link': f"https://www.upwork.com{self.link.get('href')}" if self.link else 'Data not found'
            })

        # Check for new job listings and send an email if any new jobs are found
        new_jobs = self.filter_new_jobs()
        if not new_jobs.empty:
            self.send_email(new_jobs)
            self.append_to_csv(new_jobs)

    def filter_new_jobs(self):
        '''Load existing jobs from CSV and filter out those already recorded, ignoring dynamic "Posted" column.'''
        csv_file = 'job_listings.csv'

        try:
            # Load existing jobs from CSV
            existing_jobs = pd.read_csv(csv_file)
        except FileNotFoundError:
            # If file doesn't exist, assume there are no previous jobs
            existing_jobs = pd.DataFrame(columns=['Job title', 'Posted', 'Payment info', 'Link'])

        # Convert the newly scraped data to a DataFrame
        new_jobs_df = pd.DataFrame(self.data)

        # Normalize both datasets by trimming whitespaces and converting text to lowercase
        new_jobs_df['Job title'] = new_jobs_df['Job title'].str.strip().str.lower()
        new_jobs_df['Payment info'] = new_jobs_df['Payment info'].str.strip().str.lower()
        new_jobs_df['Link'] = new_jobs_df['Link'].str.strip()

        existing_jobs['Job title'] = existing_jobs['Job title'].str.strip().str.lower()
        existing_jobs['Payment info'] = existing_jobs['Payment info'].str.strip().str.lower()
        existing_jobs['Link'] = existing_jobs['Link'].str.strip()

        # Ignore 'Posted' column when identifying duplicates
        #new_jobs_df.drop(columns=['Posted'], inplace=True)
        #existing_jobs.drop(columns=['Posted'], inplace=True)

        # Find new jobs by checking if they are not already in the CSV (based on 'Job title', 'Payment info', 'Link')
        merged_jobs = pd.merge(new_jobs_df, existing_jobs, on=['Job title', 'Payment info', 'Link'], how='left', indicator=True)
        new_jobs = merged_jobs[merged_jobs['_merge'] == 'left_only'].drop(columns=['_merge'])

        return new_jobs

    def append_to_csv(self, new_jobs):
        '''Append new job listings to the CSV file and ensure no duplicates.'''
        csv_file = 'job_listings.csv'

        # Append new jobs to the CSV file
        new_jobs.to_csv(csv_file, mode='a', header=not os.path.exists(csv_file), index=False)

        # After appending, remove any duplicates in the CSV, ignoring 'Posted' column
        all_jobs = pd.read_csv(csv_file)
        
        # Drop duplicates based on 'Job title', 'Payment info', and 'Link'
        all_jobs.drop_duplicates(subset=['Job title', 'Payment info', 'Link'], keep='first', inplace=True)
        
        # Save the deduplicated CSV back
        all_jobs.to_csv(csv_file, index=False)

        print(f"New jobs successfully appended and duplicates removed from {csv_file}")

    def send_email(self, new_jobs):
        '''Send an email containing the new job listings.'''
        load_dotenv()

        # Email setup
        sender_email = os.getenv('SENDER_EMAIL')
        receiver_email = os.getenv('RECEIVER_EMAIL')
        subject = "New Upwork Jobs Posted"
        password = os.getenv('EMAIL_PASSWORD')

        # Create the email content
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject

        # Prepare the email body
        num_new_jobs = len(new_jobs)
        body = f"""Hello,

        {num_new_jobs} new jobs have been posted on Upwork:
        """

        # Add details of each job to the email body
        for index, job in new_jobs.iterrows():
            body += f"""
        Job title: {job['Job title']}
        Payment info: {job['Payment info']}
        Link: {job['Link']}
            """

        body += "\nBest regards,\nUpWorkJobScraper"

        msg.attach(MIMEText(body, 'plain'))

        # Sending the email
        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender_email, password)
            text = msg.as_string()
            server.sendmail(sender_email, receiver_email, text)
            server.quit()
            print("Email sent successfully.")
        except Exception as e:
            print(f"Failed to send email. Error: {e}")

if __name__ == '__main__':
    URL = 'https://www.upwork.com/nx/search/jobs/?amount=100-&hourly_rate=10-&payment_verified=1&per_page=20&proposals=0-4,5-9,10-14,15-19&q=web%20scraping%20python&sort=recency&t=0,1'

    scraper = UpWorkJobScraper()
    scraper.scraping(URL)
